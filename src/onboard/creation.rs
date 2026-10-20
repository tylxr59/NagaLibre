//! Allocate an unused wired V2 Pro slot using verified firmware defaults.
use super::*;
use anyhow::Context;

pub struct PreparedCreation {
    pub backup: slot_trial::Plan,
    pub paired_backup: Option<super::layer_transaction::LayerBackup>,
}

impl<T: Transport> Mouse<T> {
    pub fn prepare_layer_creation(
        &mut self,
        known: &super::layers::LayerReadback,
        target: u8,
    ) -> Result<PreparedCreation> {
        let active = self.read_layers(None)?;
        let backup = self.capture_layer_backup(&active)?;
        ensure!(
            backup.slots.iter().any(|s| &s.state == known),
            "Mouse changed before slot creation"
        );
        ensure!(
            backup
                .slots
                .iter()
                .all(|s| s.state.normal_echoes.iter().all(|e| e.layer == 0)),
            "Create slots before configuring Hypershift, or restore the paired backup first. Existing Hypershift slots are kept"
        );
        let mut plan = self.prepare_creation(&known.normal, target)?;
        plan.paired_backup = Some(backup);
        Ok(plan)
    }

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
        Ok(PreparedCreation {
            backup,
            paired_backup: None,
        })
    }

    /// Called only after the GUI has durably saved all prepared snapshots.
    /// Keep the previous slot active. Never write any button records.
    pub fn commit_creation(&mut self, prepared: PreparedCreation) -> Result<Snapshot> {
        let paired = prepared.paired_backup;
        if let Some(before) = &paired {
            self.check_layer_backup(before)?;
        }
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
            let defaults = &crate::devices::naga_defaults().plates["12"].bindings;
            ensure!(
                defaults.len() == after.buttons.len()
                    && after
                        .buttons
                        .iter()
                        .zip(defaults)
                        .all(|(button, default)| button.category == default.category
                            && button.data == default.data),
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
            if let Some(before) = &paired {
                let mut expected = before.clone();
                for slot in &mut expected.slots {
                    slot.state.normal.slots = after.slots.clone();
                }
                self.check_layer_backup(&expected)?;
            }
            Ok(after)
        })();
        match result {
            Ok(after) => Ok(after),
            Err(error) => {
                self.cleanup_created_slot(&plan).with_context(||
                    format!("Creation failed ({error:#}); cleanup incomplete. Keep the backup and inspect mouse state before retrying"))?;
                if let Some(before) = &paired {
                    self.check_layer_backup(before).context("New slot cleaned up, but original paired records could not be verified. Keep both backups")?;
                }
                bail!(
                    "Creation failed: {error:#}. New slot removed and original tracked state verified."
                )
            }
        }
    }
}
