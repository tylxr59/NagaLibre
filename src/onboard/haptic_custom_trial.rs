//! First changed-value experiment: fixed unit velocity, existing CW/CCW intact.
//! All originals come from the independently verified CURRENT checkpoint.
use super::{
    haptic::State,
    haptic_probe::{checkpoint, target},
    haptic_transaction::Backup,
    haptic_upload_replay::packets_with_source,
    haptic_views::independent_replay_backup,
    *,
};
use serde_json::{Value, json};
use std::{
    fs::{File, OpenOptions},
    io::Read,
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::Path,
};

fn stages(state: &State) -> Result<Vec<u8>> {
    state
        .records
        .iter()
        .find(|r| r.command == 0x87)
        .map(|r| r.response.clone())
        .context("Missing original stage-list record")
}

fn candidate(original: &Backup) -> Result<Backup> {
    let before = target(original)?;
    ensure!(
        before.stages == [0x81, 0x82, 0x83, 0x84, 0x85]
            && before.active_position == 5
            && before.tables[2].len() == 3,
        "Velocity trial requires the captured five-preset Smooth baseline and three velocity points"
    );
    let mut desired = original.clone();
    let active = desired
        .slots
        .iter_mut()
        .find(|s| s.slot == original.guard.active)
        .unwrap();
    active.tables[2] = [-720f32, 0., 720.]
        .map(|x| {
            let mut point = [0; 8];
            point[..4].copy_from_slice(&x.to_le_bytes());
            point[4..].copy_from_slice(&1f32.to_le_bytes());
            point
        })
        .to_vec();
    let record = active
        .records
        .iter_mut()
        .find(|r| r.command == 0x84 && r.request.get(2) == Some(&3))
        .context("Missing independent velocity wire record")?;
    ensure!(
        record.request[..7] == [0, 6, 3, 0, 0, 0, 3] && record.response.len() == 71,
        "Velocity trial requires one exact independent three-point chunk"
    );
    for (index, point) in active.tables[2].iter().enumerate() {
        record.response[7 + index * 8..15 + index * 8].copy_from_slice(point);
    }
    Ok(desired)
}

fn selected(mut backup: Backup) -> Backup {
    let state = backup
        .slots
        .iter_mut()
        .find(|s| s.slot == backup.guard.active)
        .unwrap();
    state.stages.push(0x86);
    state.active_position = 6;
    for record in &mut state.records {
        match record.command {
            0x80 => record.response[1] = 6,
            0x87 => {
                record.response.fill(0);
                record.response[..3].copy_from_slice(&[state.slot, 6, 6]);
                record.response[3..9].copy_from_slice(&state.stages);
            }
            _ => {}
        }
    }
    backup
}

fn private_journal(path: &Path) -> Result<(File, Value)> {
    let mut file = OpenOptions::new()
        .read(true)
        .append(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let meta = file.metadata()?;
    // SAFETY: geteuid has no arguments or memory preconditions.
    let uid = unsafe { libc::geteuid() };
    ensure!(
        meta.is_file()
            && meta.len() <= 8 * 1024 * 1024
            && meta.permissions().mode() & 0o077 == 0
            && meta.uid() == uid,
        "Invalid private custom trial journal"
    );
    let mut text = String::new();
    file.read_to_string(&mut text)?;
    let first: Value =
        serde_json::from_str(text.lines().next().context("Empty custom trial journal")?)?;
    ensure!(
        !text
            .lines()
            .filter_map(|s| serde_json::from_str::<Value>(s).ok())
            .any(|v| v["stage"] == "finished" && v["details"]["restored_exactly"] == true),
        "Custom trial already restored; do not repeat it"
    );
    Ok((file, first))
}

impl<T: Transport> Mouse<T> {
    fn restore_velocity_trial(&mut self, captured: &Value, journal: &Path) -> Result<Value> {
        let mut original = independent_replay_backup(captured)?;
        let desired = selected(candidate(&original)?);
        let (mut file, first) = private_journal(journal)?;
        let mut stage_journal_errors = Vec::new();
        let mut stage_ack_errors = Vec::new();
        ensure!(
            first["stage"] == "haptic_upload_replay_pending"
                && first["details"]["independent_checkpoint"] == *captured
                && first["details"]["trial"] == "unit_velocity_v1"
                && first["details"]["backup"] == json!(original)
                && first["details"]["sequence"] == json!(packets_with_source(&original, true)?),
            "Journal does not match this velocity trial"
        );
        // Reconnect may renumber hidraw. Verify persistent identity and every
        // unrelated captured record before restoring even the stage selector.
        let guard = self.haptic_guard()?;
        original.guard.device.path = guard.device.path.clone();
        for entry in &mut original.mappings.slots {
            entry.state.normal.device.path = guard.device.path.clone();
        }
        ensure!(
            guard == original.guard,
            "Device/state changed; trial recovery refused"
        );
        self.check_layer_backup(&original.mappings)?;
        for before in &original.slots {
            if before.slot != guard.active {
                ensure!(
                    self.inspect_haptic(Some(before.slot))?.state == *before,
                    "Inactive wheel state changed"
                );
                continue;
            }
            let alternate = desired
                .slots
                .iter()
                .find(|s| s.slot == before.slot)
                .unwrap();
            let mut stage_is_original = true;
            let mut stage_is_trial = true;
            for command in [0x80, 0x87, 0x88, 0x85, 0x89] {
                let record = before
                    .records
                    .iter()
                    .find(|r| r.command == command)
                    .context("Missing unrelated record")?;
                let echo = usize::from(matches!(command, 0x80 | 0x87 | 0x89));
                let reply = self
                    .transport
                    .exchange(0x15, command, &record.request, echo)?;
                if matches!(command, 0x80 | 0x87) {
                    stage_is_original &= reply == record.response;
                    stage_is_trial &= reply
                        == alternate
                            .records
                            .iter()
                            .find(|r| r.command == command)
                            .unwrap()
                            .response;
                } else {
                    ensure!(
                        reply == record.response,
                        "Unrelated wheel field changed; recovery refused"
                    );
                }
            }
            ensure!(
                stage_is_original || stage_is_trial,
                "Wheel stage changed outside the trial"
            );
            ensure!(
                self.haptic_guard()? == guard,
                "Mouse changed before stage restoration"
            );
            if !stage_is_original {
                if let Err(error) = checkpoint(&mut file, "trial_stage_restore_pending", json!({}))
                {
                    stage_journal_errors.push(format!("{error:#}"));
                }
                // A failed ack may have landed. The full recovery's strict
                // unrelated-state check must prove original stage bytes before
                // any curve recovery; do not infer success from the ack alone.
                if let Err(error) = self.transport.exchange(0x15, 7, &stages(before)?, 0) {
                    stage_ack_errors.push(format!("{error:#}"));
                }
            }
        }
        drop(file);
        let mut result = self.replay_independent_haptic_upload(captured, journal, true)?;
        result["stage_recovery_journal_errors"] = json!(stage_journal_errors);
        result["stage_restore_ack_errors"] = json!(stage_ack_errors);
        Ok(result)
    }

    pub fn trial_haptic_unit_velocity(
        &mut self,
        captured: &Value,
        journal: &Path,
        restore: bool,
    ) -> Result<Value> {
        if restore {
            return self.restore_velocity_trial(captured, journal);
        }
        let original = independent_replay_backup(captured)?;
        let desired = candidate(&original)?;
        let sequence = packets_with_source(&desired, true)?;
        self.check_independent_haptic_backup(&original)?;
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(journal)?;
        File::open(
            journal
                .parent()
                .filter(|p| !p.as_os_str().is_empty())
                .unwrap_or(Path::new(".")),
        )?
        .sync_all()?;
        checkpoint(
            &mut file,
            "haptic_upload_replay_pending",
            json!({"backup":original,
            "sequence":packets_with_source(&original,true)?,"independent_checkpoint":captured,
            "trial":"unit_velocity_v1","candidate_sequence":sequence}),
        )?;
        self.check_independent_haptic_backup(&original)?;
        let applied = (|| -> Result<()> {
            self.send_original_upload(&sequence, &mut file, false, &mut Vec::new())?;
            self.check_independent_haptic_backup(&desired)
                .context("Verifying uploaded velocity candidate before Custom selection")?;
            let chosen = selected(desired.clone());
            checkpoint(&mut file, "trial_custom_select_pending", json!({}))?;
            let state = chosen
                .slots
                .iter()
                .find(|s| s.slot == chosen.guard.active)
                .unwrap();
            self.transport.exchange(0x15, 7, &stages(state)?, 0)?;
            self.check_independent_haptic_backup(&chosen)
                .context("Verifying candidate after Custom selection")?;
            checkpoint(&mut file, "trial_custom_applied", json!({}))?;
            Ok(())
        })();
        let mismatch = applied
            .as_ref()
            .err()
            .and_then(|error| error.downcast_ref::<super::haptic_views::IndependentStateMismatch>())
            .map(|value| json!(value));
        let mismatch_journal_error = mismatch
            .as_ref()
            .and_then(|details| {
                checkpoint(&mut file, "trial_state_mismatch", details.clone()).err()
            })
            .map(|error| format!("{error:#}"));
        drop(file);
        match applied {
            Ok(()) => Ok(
                json!({"format":1,"kind":"haptic_unit_velocity_trial_result","applied":true,
                "restored_exactly":false,"active_table_verification":"selector_zero"}),
            ),
            Err(error) => {
                let recovered = self
                    .restore_velocity_trial(captured, journal)
                    .with_context(|| {
                        format!("Trial apply failed ({error:#}); automatic recovery failed")
                    })?;
                Ok(
                    json!({"format":1,"kind":"haptic_unit_velocity_trial_result","applied":false,
                    "restored_exactly":recovered["restored_exactly"],"apply_error":format!("{error:#}"),
                    "state_mismatch":mismatch,"mismatch_journal_error":mismatch_journal_error}),
                )
            }
        }
    }
}
