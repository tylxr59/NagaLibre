//! Switch initialized profiles without writing bindings or device mode.
use super::*;
use anyhow::Context;

pub struct PreparedActivation {
    pub before: Snapshot,
    pub previous: Snapshot,
}

impl<T: Transport> Mouse<T> {
    pub fn prepare_activation(&mut self, known: &Snapshot, slot: u8) -> Result<PreparedActivation> {
        ensure!(
            &self.read(Some(known.slot))? == known,
            "Mouse state changed; read slots again before activation"
        );
        let before = self.read(Some(slot))?;
        Self::writable_snapshot(&before)?;
        ensure!(
            before.mode == [0, 0],
            "Activation requires normal mode; device mode will not be changed"
        );
        ensure!(slot != before.active, "Selected slot is already active");
        let middle = self.get_button(slot, 3, 3)?;
        ensure!(
            middle.category == 1 && middle.data == [3],
            "Selected slot lacks standard middle click"
        );
        let previous = self.read(Some(before.active))?;
        let prepared = PreparedActivation { before, previous };
        self.check_activation(&prepared)?;
        Ok(prepared)
    }

    fn check_activation(&mut self, plan: &PreparedActivation) -> Result<()> {
        let middle = self.get_button(plan.before.slot, 3, 3)?;
        ensure!(
            middle.category == 1 && middle.data == [3],
            "Selected slot lacks standard middle click"
        );
        ensure!(
            self.read(Some(plan.before.slot))? == plan.before
                && self.read(Some(plan.previous.slot))? == plan.previous,
            "Mouse state changed before activation; read slots again"
        );
        ensure!(
            plan.before.device == plan.previous.device
                && plan.before.slots == plan.previous.slots
                && plan.before.slot_capacity == plan.previous.slot_capacity
                && plan.before.mode == plan.previous.mode
                && plan.before.active == plan.previous.slot
                && plan.previous.active == plan.previous.slot,
            "Inconsistent activation state"
        );
        Ok(())
    }

    /// Caller must durably back up both snapshots before acknowledging commit.
    pub fn commit_activation(&mut self, plan: PreparedActivation) -> Result<Snapshot> {
        self.check_activation(&plan)?;
        let result = (|| -> Result<Snapshot> {
            self.activate(plan.before.slot)?;
            let after = self.read(Some(plan.before.slot))?;
            let mut expected = plan.before.clone();
            expected.active = expected.slot;
            ensure!(after == expected, "Selected slot changed during activation");
            let mut previous = plan.previous.clone();
            previous.active = after.active;
            ensure!(
                self.read(Some(previous.slot))? == previous,
                "Previous slot changed during activation"
            );
            Ok(after)
        })();
        match result {
            Ok(after) => Ok(after),
            Err(error) => {
                // A failed acknowledgement may still have switched the mouse.
                let rollback = (|| -> Result<()> {
                    self.activate(plan.previous.slot)?;
                    self.check_activation(&plan)
                })();
                rollback.with_context(|| format!("Activation failed ({error:#}); restoring the previous active slot could not be verified. Keep the backups and read mouse state"))?;
                bail!(
                    "Activation failed: {error:#}. Previous active slot restored; bindings verified unchanged."
                )
            }
        }
    }
}
