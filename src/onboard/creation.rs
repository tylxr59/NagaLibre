//! Allocate an unused wired V2 Pro slot using verified firmware defaults.
use super::*;
use anyhow::Context;

pub struct PreparedCreation {
    pub backup: slot_trial::Plan,
}

impl<T: Transport> Mouse<T> {
    pub fn prepare_creation(&mut self, before: &Snapshot, target: u8) -> Result<PreparedCreation> {
        ensure!(
            &self.read(Some(before.slot))? == before,
            "Mouse state changed; read slots again before creating a slot"
        );
        let snapshots = before
            .slots
            .iter()
            .map(|slot| self.read(Some(*slot)))
            .collect::<Result<Vec<_>>>()?;
        let backup = slot_trial::Plan {
            format: 1,
            target,
            snapshots,
        };
        self.check_trial_plan(&backup)?;
        Ok(PreparedCreation { backup })
    }

    /// Called only after the GUI has durably saved all prepared snapshots.
    /// Keep the previous slot active. Never write any button records.
    pub fn commit_creation(&mut self, prepared: PreparedCreation) -> Result<Snapshot> {
        let plan = prepared.backup;
        self.check_trial_plan(&plan)?;
        let result = (|| -> Result<Snapshot> {
            self.transport.exchange(5, 2, &[plan.target], 0)?;
            let after = self.read(Some(plan.target))?;
            let original = &plan.snapshots[0];
            let mut slots = original.slots.clone();
            slots.push(plan.target);
            slots.sort_unstable();
            let mut actual = after.slots.clone();
            actual.sort_unstable();
            ensure!(
                actual == slots
                    && after.slot_capacity == original.slot_capacity
                    && after.active == original.active
                    && after.mode == original.mode,
                "Unexpected state after slot creation"
            );
            Self::writable_snapshot(&after)?;
            let middle = self.get_button(plan.target, 3, 3)?;
            ensure!(
                middle.category == 1 && middle.data == [3],
                "New slot lacks standard middle click"
            );
            let usages = [
                0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x2d, 0x2e,
            ];
            ensure!(
                after
                    .buttons
                    .iter()
                    .zip(usages)
                    .all(|(button, usage)| button.category == 2 && button.data == [0, usage]),
                "New slot defaults differ from the verified wired firmware"
            );
            for before in &plan.snapshots {
                let fresh = self.read(Some(before.slot))?;
                let mut expected = before.clone();
                expected.slots = after.slots.clone();
                ensure!(
                    fresh == expected,
                    "Existing slot {} changed during allocation",
                    before.slot
                );
            }
            Ok(after)
        })();
        match result {
            Ok(after) => Ok(after),
            Err(error) => {
                self.cleanup_created_slot(&plan).with_context(||
                    format!("Creation failed ({error:#}); cleanup incomplete. Keep the backup and inspect mouse state before retrying"))?;
                bail!(
                    "Creation failed: {error:#}. New slot removed and original tracked state verified."
                )
            }
        }
    }
}
