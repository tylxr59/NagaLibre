//! One-record recovery for the captured grid-1 reverse-echo failure, not a bank editor.
use super::{layer_transaction::LayerBackup, *};
use serde_json::{Value, json};
use std::{fs::OpenOptions, io::Write, os::unix::fs::OpenOptionsExt, path::Path};

fn same_capture(mut actual: Value, expected: &Value) -> bool {
    actual["metadata"]["device"]["path"] = expected["metadata"]["device"]["path"].clone();
    &actual == expected
}

impl<T: Transport> Mouse<T> {
    fn check_echo_recovery(&mut self, backup: &LayerBackup, evidence: &Value) -> Result<()> {
        ensure!(
            backup.format == 1 && backup.kind == "paired_mapping_backup",
            "Invalid paired backup"
        );
        ensure!(
            evidence["format"] == 1
                && evidence["kind"] == "unverified_selector_observations"
                && evidence["bank_identity_verified"] == false
                && evidence["slot"] == 1,
            "Recovery is restricted to the captured slot-1 diagnostic"
        );
        let fresh = self.inspect_mapping_selectors()?;
        ensure!(
            same_capture(fresh.clone(), evidence),
            "Mouse differs from saved recovery evidence; no repair attempted"
        );
        let active = backup
            .slots
            .iter()
            .find(|s| s.state.normal.slot == 1)
            .context("Missing slot-1 paired backup")?;
        let normal = &active.state.normal;
        ensure!(
            normal.device.product == 0xa7 && normal.slot == normal.active && normal.mode == [0, 0],
            "Echo recovery requires wired active slot 1 in normal mode"
        );
        let serial: Vec<_> = normal
            .device
            .serial
            .bytes()
            .chain(std::iter::repeat(0))
            .take(22)
            .collect();
        ensure!(
            !normal.device.serial.is_empty()
                && fresh["metadata"]["serial_bytes"] == json!(serial)
                && fresh["metadata"]["device"]["product"] == 0xa7
                && fresh["metadata"]["mode"] == json!(normal.mode)
                && fresh["metadata"]["inventory"]
                    == json!({"capacity":normal.slot_capacity.context("Missing capacity")?,
                "initialized":normal.slots,"active":1}),
            "Recovery identity or tracked state changed"
        );
        let backed_up: BTreeSet<_> = backup.slots.iter().map(|s| s.state.normal.slot).collect();
        ensure!(
            backed_up.len() == backup.slots.len()
                && backed_up == normal.slots.iter().copied().collect(),
            "Incomplete all-slot paired backup"
        );
        for saved in &backup.slots {
            super::layer_transaction::validate_state(&saved.state)?;
            let n = &saved.state.normal;
            ensure!(
                n.device == normal.device
                    && n.slots == normal.slots
                    && n.active == normal.active
                    && n.mode == normal.mode
                    && n.slot_capacity == normal.slot_capacity,
                "Inconsistent paired backup"
            );
            if n.slot != 1 {
                self.check_restored_layer_slot(saved)?;
            }
        }
        // This accepts no changed action bytes. Only grid 1's echoed selector
        // may differ, and it must be 1 for both requested selectors as captured.
        let records = fresh["records"]
            .as_array()
            .context("Missing recovery records")?;
        ensure!(records.len() == 35, "Incomplete recovery records");
        for record in records {
            let layer = record["requested_layer"]
                .as_u64()
                .context("Missing selector")?;
            let wire = record["wire"].as_u64().context("Missing wire address")?;
            let (original, echo) = if record["logical"].is_null() {
                ensure!(layer == 0, "Secondary primary recovery is forbidden");
                let b = normal
                    .primary
                    .iter()
                    .chain(std::iter::once(&active.middle))
                    .find(|b| u64::from(b.button) == wire)
                    .context("Invalid primary observation")?;
                (b, 0)
            } else {
                ensure!(layer <= 1, "Invalid recovery selector");
                let logical = record["logical"]
                    .as_u64()
                    .context("Invalid logical address")?;
                let entries = if layer == 0 {
                    normal.buttons.iter().chain(&normal.controls)
                } else {
                    active
                        .state
                        .hypershift
                        .buttons
                        .iter()
                        .chain(&active.state.hypershift.controls)
                };
                let b = entries
                    .into_iter()
                    .find(|b| u64::from(b.button) == logical)
                    .context("Unknown recovery address")?;
                ensure!(
                    u64::from(control_id(b.button)?) == wire,
                    "Recovery address mismatch"
                );
                let echo = if logical == 1 {
                    1
                } else if layer == 0 {
                    0
                } else {
                    active
                        .state
                        .hypershift
                        .echoes
                        .iter()
                        .find(|e| u64::from(e.button) == logical)
                        .context("Missing original selector echo")?
                        .layer
                };
                (b, echo)
            };
            ensure!(
                record["record"] == json!(original.record()?) && record["echoed_layer"] == echo,
                "Recovery is limited to unchanged action bytes and the captured grid-1 echo mismatch"
            );
        }
        Ok(())
    }

    pub(super) fn check_restored_layer_slot(
        &mut self,
        saved: &super::layer_transaction::LayerSlotBackup,
    ) -> Result<()> {
        let mut fresh = self.read_layers(Some(saved.state.normal.slot))?;
        fresh
            .normal
            .device
            .path
            .clone_from(&saved.state.normal.device.path);
        ensure!(
            fresh == saved.state && self.get_button(saved.state.normal.slot, 3, 3)? == saved.middle,
            "Paired backup is not exactly restored in slot {}",
            saved.state.normal.slot
        );
        Ok(())
    }

    /// Backup/evidence are already durable user files. A create-new, fsynced
    /// journal prevents repeating this repair after a lost acknowledgement.
    pub fn recover_grid_one_echo(
        &mut self,
        backup: &LayerBackup,
        evidence: &Value,
        journal: &Path,
    ) -> Result<()> {
        self.check_echo_recovery(backup, evidence)?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(journal)
            .context("Creating one-attempt echo recovery journal")?;
        std::fs::File::open(journal.parent().context("Missing journal parent")?)?.sync_all()?;
        let mut checkpoint = |stage: &str, error: Option<String>| -> Result<()> {
            serde_json::to_writer(
                &mut file,
                &json!({"stage":stage,"backup":backup,"evidence":evidence,"error":error}),
            )?;
            file.write_all(b"\n")?;
            file.sync_all()?;
            Ok(())
        };
        checkpoint("normal_grid_1_repair_pending", None)?;
        self.check_echo_recovery(backup, evidence)?;
        let saved = backup
            .slots
            .iter()
            .find(|s| s.state.normal.slot == 1)
            .unwrap();
        // The sole writer uses selector 0 and the exact original normal record.
        // Never replay a selector-1 record to recover this selector mismatch.
        let write = self.set_button(1, &saved.state.normal.buttons[0], Verification::Wire);
        let error = write.err().map(|e| format!("{e:#}"));
        checkpoint("normal_grid_1_repair_attempted", error.clone())?;
        // A lost acknowledgement can still have landed: always check the full
        // paired backup, including actual echo metadata, before reporting success.
        for slot in &backup.slots {
            if let Err(failure) = self.check_restored_layer_slot(slot) {
                checkpoint("repair_unverified", Some(format!("{failure:#}")))?;
                bail!(
                    "Grid-1 echo repair was attempted; full restoration remains unverified: {failure:#}. Keep the journal and collect fresh selector evidence"
                );
            }
        }
        checkpoint("paired_backup_restored_exactly", error)?;
        Ok(())
    }
}
