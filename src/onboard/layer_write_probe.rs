//! A single secondary write with observation and unconditional exact restoration.
use super::{layer_transaction::LayerBackup, *};
use serde_json::{Value, json};
use std::{fs::OpenOptions, io::Write, os::unix::fs::OpenOptionsExt, path::Path};

impl<T: Transport> Mouse<T> {
    fn validate_write_probe_backup(backup: &LayerBackup) -> Result<()> {
        ensure!(
            backup.format == 1 && backup.kind == "paired_mapping_backup",
            "Invalid paired backup"
        );
        let first = backup
            .slots
            .iter()
            .find(|s| s.state.normal.slot == 1)
            .context("Missing slot 1")?;
        let n = &first.state.normal;
        ensure!(
            n.device.product == 0xa7
                && !n.device.serial.is_empty()
                && n.slot == n.active
                && n.mode == [0, 0],
            "Write probe requires wired active slot 1 in normal mode"
        );
        let slots: BTreeSet<_> = backup.slots.iter().map(|s| s.state.normal.slot).collect();
        ensure!(
            slots.len() == backup.slots.len() && slots == n.slots.iter().copied().collect(),
            "Incomplete probe backup"
        );
        for saved in &backup.slots {
            super::layer_transaction::validate_state(&saved.state)?;
            let other = &saved.state.normal;
            ensure!(
                other.device == n.device
                    && other.slots == n.slots
                    && other.active == n.active
                    && other.mode == n.mode
                    && other.slot_capacity == n.slot_capacity,
                "Inconsistent probe backup"
            );
        }
        Ok(())
    }

    fn check_write_probe_backup(&mut self, backup: &LayerBackup) -> Result<Value> {
        Self::validate_write_probe_backup(backup)?;
        let first = backup
            .slots
            .iter()
            .find(|s| s.state.normal.slot == 1)
            .unwrap();
        let n = &first.state.normal;
        for saved in &backup.slots {
            self.check_restored_layer_slot(saved)?;
        }
        let capture = self.inspect_mapping_selectors()?;
        let mut expected = capture.clone();
        for record in expected["records"]
            .as_array_mut()
            .context("Missing observations")?
        {
            let layer = record["requested_layer"]
                .as_u64()
                .context("Invalid selector")?;
            let (button, echo) = if let Some(logical) = record["logical"].as_u64() {
                let bank = if layer == 0 {
                    n.buttons.iter().chain(&n.controls)
                } else {
                    first
                        .state
                        .hypershift
                        .buttons
                        .iter()
                        .chain(&first.state.hypershift.controls)
                };
                let button = bank
                    .into_iter()
                    .find(|b| u64::from(b.button) == logical)
                    .context("Invalid control")?;
                let echo = if layer == 0 {
                    0
                } else {
                    first
                        .state
                        .hypershift
                        .echoes
                        .iter()
                        .find(|e| u64::from(e.button) == logical)
                        .context("Missing echo")?
                        .layer
                };
                (button, echo)
            } else {
                let id = record["wire"].as_u64().context("Missing primary ID")?;
                let button = n
                    .primary
                    .iter()
                    .chain(std::iter::once(&first.middle))
                    .find(|b| u64::from(b.button) == id)
                    .context("Invalid primary")?;
                (button, 0)
            };
            record["record"] = json!(button.record()?);
            record["echoed_layer"] = json!(echo);
        }
        ensure!(
            capture == expected,
            "Selector observations differ from paired backup"
        );
        Ok(capture)
    }

    /// Diagnostic result only: verifies observed data selection, not physical Hypershift.
    /// The writer always restores secondary first and normal last, including on
    /// lost acknowledgements. Never installs a trigger or changes another control.
    pub fn layer_write_probe(
        &mut self,
        backup: &LayerBackup,
        journal: &Path,
        restore_only: bool,
    ) -> Result<Value> {
        Self::validate_write_probe_backup(backup)?;
        if restore_only {
            // A retry is restoration only, with data read from the durable journal.
            // Never create a second B write after an interrupted attempt.
            ensure!(journal.exists(), "No probe attempt journal exists");
            let text = std::fs::read_to_string(journal)?;
            let first: Value =
                serde_json::from_str(text.lines().next().context("Empty probe journal")?)?;
            ensure!(
                first["stage"] == "probe_write_pending" && first["backup"] == json!(backup),
                "Probe journal does not match backup"
            );
            let observed = self.inspect_mapping_selectors()?;
            let mut expected = first["details"].clone();
            expected["metadata"]["device"]["path"] = observed["metadata"]["device"]["path"].clone();
            let target = backup
                .slots
                .iter()
                .find(|s| s.state.normal.slot == 1)
                .unwrap();
            let serial: Vec<_> = target
                .state
                .normal
                .device
                .serial
                .bytes()
                .chain(std::iter::repeat(0))
                .take(22)
                .collect();
            ensure!(
                observed["metadata"]["serial_bytes"] == json!(serial)
                    && observed["metadata"]["device"]["product"] == 0xa7,
                "Probe restore belongs to another mouse or connection"
            );
            let originals = expected["records"]
                .as_array_mut()
                .context("Invalid probe checkpoint")?;
            let actuals = observed["records"]
                .as_array()
                .context("Missing current records")?;
            ensure!(
                originals.len() == 35 && actuals.len() == 35,
                "Incomplete restore observations"
            );
            for (original, actual) in originals.iter_mut().zip(actuals) {
                if original["logical"] == 1 {
                    let raw: [u8; 7] = serde_json::from_value(actual["record"].clone())?;
                    let decoded = Button::from_record(1, raw)?;
                    ensure!(
                        actual["record"] == original["record"]
                            || (decoded.category == 2 && decoded.data == [0, 5]),
                        "Unexpected target action during restore"
                    );
                    original["record"] = actual["record"].clone();
                    original["echoed_layer"] = actual["echoed_layer"].clone();
                }
            }
            ensure!(
                expected == observed,
                "Unrelated state changed; probe restore stopped"
            );
            for other in &backup.slots {
                if other.state.normal.slot != 1 {
                    self.check_restored_layer_slot(other)?;
                }
            }
        }
        let baseline = if restore_only {
            None
        } else {
            Some(self.check_write_probe_backup(backup)?)
        };
        let mut file = if restore_only {
            OpenOptions::new().append(true).open(journal)?
        } else {
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(journal)?
        };
        std::fs::File::open(journal.parent().context("Missing journal parent")?)?.sync_all()?;
        let mut checkpoint = |stage: &str, details: Value| -> Result<()> {
            serde_json::to_writer(
                &mut file,
                &json!({"stage":stage,"backup":backup,"details":details}),
            )?;
            file.write_all(b"\n")?;
            file.sync_all()?;
            Ok(())
        };
        if let Some(before) = &baseline {
            checkpoint("probe_write_pending", before.clone())?;
            ensure!(
                self.check_write_probe_backup(backup)? == *before,
                "State changed after probe checkpoint; no write attempted"
            );
        }
        let saved = backup
            .slots
            .iter()
            .find(|s| s.state.normal.slot == 1)
            .context("Missing probe slot")?;
        let normal = &saved.state.normal.buttons[0];
        let secondary = &saved.state.hypershift.buttons[0];
        let result = (|| -> Result<Value> {
            if restore_only {
                return Ok(json!({"restoration_only":true}));
            }
            let mut payload = [0; 10];
            payload[..3].copy_from_slice(&[1, control_id(1)?, 1]);
            payload[3..].copy_from_slice(&[2, 2, 0, 5, 0, 0, 0]); // Native keyboard B encoding.
            // One send only; a lost acknowledgement still enters restoration.
            self.transport.exchange(2, 0x0c, &payload, 0)?;
            let observed = self.inspect_mapping_selectors()?;
            checkpoint("probe_observed", observed.clone())?;
            let before = baseline.as_ref().unwrap();
            let mut expected = before.clone();
            // Only grid 1's two returned selector bytes may change. Retain the
            // actual values as evidence, while checking all action bytes.
            for (want, actual) in expected["records"].as_array_mut().unwrap().iter_mut().zip(
                observed["records"]
                    .as_array()
                    .context("Missing observations")?,
            ) {
                if want["logical"] == 1 {
                    want["echoed_layer"] = actual["echoed_layer"].clone();
                    if want["requested_layer"] == 1 {
                        // Match decoded B, retaining any firmware reencoding.
                        let raw: [u8; 7] = serde_json::from_value(actual["record"].clone())?;
                        let decoded = Button::from_record(1, raw)?;
                        ensure!(
                            decoded.category == 2 && decoded.data == [0, 5],
                            "Selector 1 did not return B"
                        );
                        want["record"] = actual["record"].clone();
                    }
                }
            }
            ensure!(
                expected == observed,
                "Normal action, unrelated controls or metadata changed during probe"
            );
            for other in &backup.slots {
                if other.state.normal.slot != 1 {
                    self.check_restored_layer_slot(other)?;
                }
            }
            Ok(json!({"observed_selector_1_b_only":true,"observations":observed}))
        })();
        // A changed plate cannot safely receive the twelve-button grid write.
        ensure!(
            crate::faceplate::read(self)?.buttons == Some(12),
            "Faceplate changed; probe restoration is pending. Keep the journal"
        );
        // Never let an observation/checkpoint error skip the original writes.
        let mut errors = Vec::new();
        for (layer, original) in [(1, secondary), (0, normal)] {
            let mut payload = [0; 10];
            payload[..3].copy_from_slice(&[1, control_id(1)?, layer]);
            payload[3..].copy_from_slice(&original.record()?);
            if let Err(error) = self.transport.exchange(2, 0x0c, &payload, 0) {
                errors.push(format!("{error:#}"));
            }
        }
        let restored = self.check_write_probe_backup(backup);
        if let Err(error) = restored {
            let _ = checkpoint(
                "probe_restore_unverified",
                json!({"error":format!("{error:#}"),"write_errors":errors}),
            );
            bail!(
                "Probe restoration could not be verified: {error:#}. Keep the journal and run the restore stage"
            );
        }
        checkpoint("probe_restored_exactly", json!({"write_errors":errors}))?;
        let report =
            result.context("Probe failed, but original paired backup was restored and verified")?;
        Ok(json!({"restored_exactly":true,"result":report}))
    }
}
