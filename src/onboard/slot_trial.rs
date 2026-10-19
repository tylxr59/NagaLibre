//! Controlled, temporary allocation experiment. This is not a profile editor.
use super::*;
use anyhow::Context;
use std::{fs::OpenOptions, io::Write, os::unix::fs::OpenOptionsExt, path::Path};

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    pub format: u8,
    pub target: u8,
    pub snapshots: Vec<Snapshot>,
}

fn same_device_state(mut actual: Snapshot, expected: &Snapshot) -> bool {
    // hidraw numbering may change between preparation and execution.
    actual.device.path.clone_from(&expected.device.path);
    &actual == expected
}

impl<T: Transport> Mouse<T> {
    pub(super) fn check_trial_plan(&mut self, plan: &Plan) -> Result<()> {
        ensure!(plan.format == 1, "Unsupported trial plan");
        slot_valid(plan.target)?;
        ensure!(plan.target > 1, "Slot 1 cannot be a trial target");
        let first = plan.snapshots.first().context("Empty trial backup")?;
        ensure!(
            first.device.product == 0xa7,
            "Trial requires the wired V2 Pro"
        );
        ensure!(first.mode == [0, 0], "Trial requires normal mode");
        Self::writable_snapshot(first)?;
        ensure!(
            !first.slots.contains(&plan.target)
                && first.slot_capacity.is_some_and(|n| plan.target <= n),
            "Trial target must be unused and within reported capacity"
        );
        let backed_up: BTreeSet<_> = plan.snapshots.iter().map(|s| s.slot).collect();
        ensure!(
            backed_up == first.slots.iter().copied().collect()
                && backed_up.len() == plan.snapshots.len(),
            "Every initialized slot must have exactly one backup"
        );
        for expected in &plan.snapshots {
            ensure!(
                expected.device == first.device
                    && expected.slots == first.slots
                    && expected.active == first.active
                    && expected.mode == first.mode
                    && expected.slot_capacity == first.slot_capacity,
                "Inconsistent trial backups"
            );
            ensure!(
                same_device_state(self.read(Some(expected.slot))?, expected),
                "Mouse changed since backup; no allocation attempted"
            );
        }
        Ok(())
    }

    /// The caller must durably save the plan before calling.
    /// The journal is created exclusively before the first vendor mutation.
    /// No button mappings, profile metadata or device mode are written.
    pub fn slot_trial(&mut self, plan: &Plan, journal: &Path) -> Result<()> {
        self.check_trial_plan(plan)?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(journal)?;
        let parent = journal
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        std::fs::File::open(parent)?.sync_all()?;
        let mut record = |value: serde_json::Value| -> Result<()> {
            serde_json::to_writer(&mut file, &value)?;
            file.write_all(b"\n")?;
            file.sync_all()?;
            Ok(())
        };
        record(serde_json::json!({"stage":"allocation_pending", "plan":plan}))?;
        // Recheck after the durable journal and immediately before allocation.
        self.check_trial_plan(plan)?;
        let original = &plan.snapshots[0];
        let inspection = (|| -> Result<_> {
            // Device167 CProtocol25::AddProfile (RVA 0x282d0).
            // Do not retry: a failed acknowledgement may still allocate.
            self.transport.exchange(5, 2, &[plan.target], 0)?;
            let inventory = self.slot_inventory()?;
            let mut expected = original.slots.clone();
            expected.push(plan.target);
            expected.sort_unstable();
            let mut actual = inventory.initialized.clone();
            actual.sort_unstable();
            ensure!(
                actual == expected && Some(inventory.capacity) == original.slot_capacity,
                "Unexpected inventory after allocation"
            );
            ensure!(
                inventory.active == original.active,
                "Allocation changed the active slot"
            );
            ensure!(
                self.get_mode()? == original.mode,
                "Allocation changed device mode"
            );
            let snapshot = self.read(Some(plan.target))?;
            let middle = self.get_button(plan.target, 3, 3)?;
            // Save defaults BEFORE removal, including exact wire encodings.
            record(
                serde_json::json!({"stage":"defaults_read", "snapshot":snapshot, "middle":middle}),
            )?;
            Ok(())
        })();
        // Always inspect/clean up after an attempted allocation, even if its
        // acknowledgement or the journal write failed. Never delete an old slot.
        let cleanup = self.cleanup_created_slot(plan);
        record(
            serde_json::json!({"stage":"finished", "inspection_error":inspection.as_ref().err().map(|e|format!("{e:#}")),
            "cleanup_error":cleanup.as_ref().err().map(|e|format!("{e:#}"))}),
        )?;
        cleanup.context("Temporary-slot cleanup or original-state verification failed")?;
        inspection
            .context("Defaults inspection failed; original tracked state verified after cleanup")?;
        Ok(())
    }
    pub(super) fn cleanup_created_slot(&mut self, plan: &Plan) -> Result<()> {
        let original = &plan.snapshots[0];
        let inventory = self.slot_inventory()?;
        ensure!(
            Some(inventory.capacity) == original.slot_capacity,
            "Capacity changed; inspect manually"
        );
        let old: BTreeSet<_> = original.slots.iter().copied().collect();
        let current: BTreeSet<_> = inventory.initialized.iter().copied().collect();
        let mut permitted = old.clone();
        permitted.insert(plan.target);
        ensure!(
            old.is_subset(&current) && current.is_subset(&permitted),
            "Other slots changed; refusing automatic cleanup"
        );
        if inventory.active != original.active {
            ensure!(
                inventory.active == plan.target,
                "Unexpected active slot; inspect manually"
            );
            self.activate(original.active)?;
        }
        if current.contains(&plan.target) {
            // Device167 CProtocol25::RemoveProfile (RVA 0x2d230).
            // Verify even on a failed acknowledgement; never retry deletion.
            let deletion = self.transport.exchange(5, 3, &[plan.target], 0);
            let after = self.slot_inventory()?;
            ensure!(
                !after.initialized.contains(&plan.target),
                "Temporary slot remains; deletion response: {deletion:?}"
            );
        }
        for expected in &plan.snapshots {
            ensure!(
                same_device_state(self.read(Some(expected.slot))?, expected),
                "Original slot {} differs after cleanup; keep backups and inspect manually",
                expected.slot
            );
        }
        Ok(())
    }
}
