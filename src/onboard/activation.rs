//! Switch initialized profiles without writing bindings or device mode.
use super::*;
use anyhow::Context;

pub struct PreparedActivation {
    pub before: Snapshot,
    pub previous: Snapshot,
}

pub struct PreparedLayerActivation {
    pub backup: super::layer_transaction::LayerBackup,
    target: u8,
}

impl<T: Transport> Mouse<T> {
    pub fn prepare_layer_activation(
        &mut self,
        known: &super::layers::LayerReadback,
        slot: u8,
    ) -> Result<PreparedLayerActivation> {
        slot_valid(slot)?;
        let active = self.read_layers(None)?;
        let backup = self.capture_layer_backup(&active)?;
        ensure!(
            backup.slots.iter().any(|s| &s.state == known),
            "Paired state changed before activation"
        );
        let target = backup
            .slots
            .iter()
            .find(|s| s.state.normal.slot == slot)
            .context("Target slot is uninitialized")?;
        ensure!(
            slot != active.normal.active,
            "Selected slot is already active"
        );
        Self::writable_snapshot(&target.state.normal)?;
        ensure!(
            target.middle.category == 1 && target.middle.data == [3],
            "Target lacks standard middle click"
        );
        Ok(PreparedLayerActivation {
            backup,
            target: slot,
        })
    }

    pub fn commit_layer_activation(
        &mut self,
        plan: PreparedLayerActivation,
    ) -> Result<super::layers::LayerReadback> {
        self.check_layer_backup(&plan.backup)?;
        let previous = plan.backup.slots[0].state.normal.active;
        let result = (|| -> Result<super::layers::LayerReadback> {
            self.activate(plan.target)?;
            let mut expected = plan.backup.clone();
            for slot in &mut expected.slots {
                slot.state.normal.active = plan.target;
            }
            self.check_layer_backup(&expected)?;
            self.read_layers(Some(plan.target))
        })();
        match result {
            Ok(after) => Ok(after),
            Err(error) => {
                // A lost acknowledgement may have switched the active slot.
                let _ = self.activate(previous);
                self.check_layer_backup(&plan.backup).with_context(|| format!("Activation failed ({error:#}); previous active slot and paired records could not be verified. Keep the paired backup"))?;
                bail!(
                    "Activation failed ({error:#}); previous slot and all paired records restored and verified"
                )
            }
        }
    }

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
