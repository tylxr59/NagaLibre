//! Paired-bank transactions for the wired, active-slot controlled trial.
use super::{layers::LayerReadback, *};

/// Distinct from diagnostic exports and legacy normal-only mapping backups.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LayerBackup {
    pub format: u8,
    pub kind: String,
    pub slots: Vec<LayerSlotBackup>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LayerSlotBackup {
    pub state: LayerReadback,
    pub middle: Button,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LayerEdit {
    pub layer: u8,
    pub action: Button,
}

pub struct PreparedLayers {
    // Read-only accessor prevents a caller from replacing the checked backup.
    before: LayerBackup,
    target: LayerReadback,
    desired: LayerReadback,
    verification: Verification,
}

impl PreparedLayers {
    /// The unprivileged caller must durably save this before acknowledging commit.
    pub fn backup(&self) -> &LayerBackup {
        &self.before
    }
}

fn records(state: &LayerReadback, layer: u8) -> impl Iterator<Item = &Button> {
    let (buttons, controls) = if layer == 0 {
        (&state.normal.buttons, &state.normal.controls)
    } else {
        (&state.hypershift.buttons, &state.hypershift.controls)
    };
    buttons.iter().chain(controls)
}

pub(super) fn validate_state(state: &LayerReadback) -> Result<()> {
    ensure!(
        state.format == 1
            && state.normal.format == 1
            && state.hypershift.layer == 1
            && !state.hypershift.primary_inspected,
        "Invalid paired-bank state"
    );
    slot_valid(state.normal.slot)?;
    for layer in 0..=1 {
        let entries: Vec<_> = records(state, layer).collect();
        ensure!(entries.len() == 16, "Incomplete paired-bank records");
        for (index, button) in entries.into_iter().enumerate() {
            ensure!(
                button.button == index as u8 + 1,
                "Invalid paired-bank address order"
            );
            control_id(button.button)?;
            button.record()?;
        }
    }
    ensure!(
        state.normal_echoes.len() == 16,
        "Incomplete normal echo metadata"
    );
    for (index, echo) in state.normal_echoes.iter().enumerate() {
        ensure!(
            echo.button == index as u8 + 1 && echo.layer <= 1,
            "Invalid normal echo"
        );
    }
    ensure!(
        state.hypershift.echoes.len() == 16,
        "Incomplete bank echoes"
    );
    for (index, echo) in state.hypershift.echoes.iter().enumerate() {
        ensure!(
            echo.button == index as u8 + 1 && echo.layer <= 1,
            "Invalid bank echo"
        );
    }
    Ok(())
}

impl<T: Transport> Mouse<T> {
    fn layer_write_scope(state: &LayerReadback) -> Result<()> {
        validate_state(state)?;
        Self::writable_snapshot(&state.normal)?;
        ensure!(
            state.normal.device.product == 0xa7,
            "Initial layer transactions require wired Naga V2 Pro"
        );
        ensure!(
            state.normal.slot == state.normal.active && state.normal.mode == [0, 0],
            "Layer transactions require the active slot in normal mode"
        );
        Ok(())
    }

    pub(super) fn capture_layer_backup(&mut self, target: &LayerReadback) -> Result<LayerBackup> {
        Self::layer_write_scope(target)?;
        let mut slots = Vec::new();
        for slot in &target.normal.slots {
            let state = self.read_layers(Some(*slot))?;
            ensure!(
                state.normal.device == target.normal.device
                    && state.normal.slots == target.normal.slots
                    && state.normal.active == target.normal.active
                    && state.normal.mode == target.normal.mode,
                "Device state changed while backing up layers"
            );
            if *slot == target.normal.slot {
                ensure!(
                    &state == target,
                    "Layer state changed; read both banks again"
                );
            }
            slots.push(LayerSlotBackup {
                state,
                middle: self.get_button(*slot, 3, 3)?,
            });
        }
        let backup = LayerBackup {
            format: 1,
            kind: "paired_mapping_backup".into(),
            slots,
        };
        self.check_layer_backup(&backup)?;
        let middle = &backup
            .slots
            .iter()
            .find(|s| s.state.normal.slot == target.normal.slot)
            .context("Missing active-slot backup")?
            .middle;
        ensure!(
            middle.category == 1 && middle.data == [3],
            "Active slot lacks standard middle click"
        );
        Ok(backup)
    }

    pub(super) fn check_layer_backup(&mut self, backup: &LayerBackup) -> Result<()> {
        for slot in &backup.slots {
            ensure!(
                self.read_layers(Some(slot.state.normal.slot))? == slot.state
                    && self.get_button(slot.state.normal.slot, 3, 3)? == slot.middle,
                "Paired-bank state changed; no settings were written"
            );
        }
        Ok(())
    }

    /// Sparse edits preserve every unspecified record, including unknown actions.
    /// Trigger encoding is allowed only in the normal bank; nested triggers are
    /// outside the initial scope. No mode, slot inventory or activation writes.
    pub fn prepare_layers(
        &mut self,
        known: &LayerReadback,
        edits: Vec<LayerEdit>,
    ) -> Result<PreparedLayers> {
        Self::layer_write_scope(known)?;
        let mut desired = known.clone();
        let mut seen = BTreeSet::new();
        ensure!(edits.len() <= 32, "Too many layer edits");
        for edit in edits {
            ensure!(
                edit.layer <= 1 && seen.insert((edit.layer, edit.action.button)),
                "Invalid or duplicate layer edit"
            );
            control_id(edit.action.button)?;
            // User edits are canonical. Only backup restoration can request
            // unknown encodings or nonstandard trailing bytes.
            ensure!(
                edit.action.raw_record.is_none(),
                "Raw records require paired backup restoration"
            );
            let normal_factory = edit.layer == 0
                && crate::devices::naga_defaults().controls.iter().any(|c| {
                    c.button == edit.action.button
                        && c.binding.category == edit.action.category
                        && c.binding.data == edit.action.data
                });
            if !(normal_factory
                || edit.layer == 0 && edit.action.category == 0x0c && edit.action.data == [1])
            {
                validate_action(&edit.action)?;
            }
            let entries = if edit.layer == 0 {
                if edit.action.button <= 12 {
                    &mut desired.normal.buttons
                } else {
                    &mut desired.normal.controls
                }
            } else if edit.action.button <= 12 {
                &mut desired.hypershift.buttons
            } else {
                &mut desired.hypershift.controls
            };
            let original = entries
                .iter_mut()
                .find(|b| b.button == edit.action.button)
                .context("Missing layer record")?;
            if !original.same_action(&edit.action) {
                *original = edit.action;
            }
        }
        // Wired capture proved both replies can carry the last written selector.
        // Predict only tags of records this plan actually changes; preserve all
        // other metadata exactly, including stale-check and restoration inputs.
        for layer in [1, 0] {
            let changed: Vec<_> = records(known, layer)
                .zip(records(&desired, layer))
                .filter_map(|(before, after)| (before != after).then_some(after.button))
                .collect();
            for button in changed {
                desired
                    .normal_echoes
                    .iter_mut()
                    .find(|e| e.button == button)
                    .unwrap()
                    .layer = layer;
                desired
                    .hypershift
                    .echoes
                    .iter_mut()
                    .find(|e| e.button == button)
                    .unwrap()
                    .layer = layer;
            }
        }
        let before = self.capture_layer_backup(known)?;
        Ok(PreparedLayers {
            before,
            target: known.clone(),
            desired,
            verification: Verification::Action,
        })
    }

    /// Restore only this transaction's active-slot mappings. All other slots,
    /// device mode, inventory and primary clicks must still match the backup.
    pub fn prepare_layers_restore(&mut self, backup: &LayerBackup) -> Result<PreparedLayers> {
        ensure!(
            backup.format == 1 && backup.kind == "paired_mapping_backup",
            "Invalid paired mapping backup"
        );
        let active = self.read_layers(None)?;
        Self::layer_write_scope(&active)?;
        ensure!(
            backup.slots.len() == active.normal.slots.len(),
            "Paired backup inventory changed"
        );
        let mut seen = BTreeSet::new();
        let mut desired = None;
        for saved in &backup.slots {
            validate_state(&saved.state)?;
            let normal = &saved.state.normal;
            ensure!(
                seen.insert(normal.slot) && active.normal.slots.contains(&normal.slot),
                "Invalid backup slots"
            );
            ensure!(
                !normal.device.serial.is_empty()
                    && normal.device.serial == active.normal.device.serial
                    && normal.device.product == active.normal.device.product,
                "Paired backup belongs to another mouse or connection"
            );
            let fresh = self.read_layers(Some(normal.slot))?;
            // Bind the validated backup to today's path; reconnect can renumber hidraw.
            let mut rebound = saved.state.clone();
            rebound.normal.device = fresh.normal.device.clone();
            let mut unchanged = rebound.clone();
            if normal.slot == active.normal.slot {
                unchanged.normal_echoes = fresh.normal_echoes.clone();
                unchanged.hypershift.echoes = fresh.hypershift.echoes.clone();
                unchanged.normal.buttons = fresh.normal.buttons.clone();
                unchanged.normal.controls = fresh.normal.controls.clone();
                unchanged.hypershift.buttons = fresh.hypershift.buttons.clone();
                unchanged.hypershift.controls = fresh.hypershift.controls.clone();
                desired = Some(rebound);
            }
            ensure!(
                fresh == unchanged && self.get_button(normal.slot, 3, 3)? == saved.middle,
                "Non-mapping state or another slot differs from paired backup"
            );
        }
        let before = self.capture_layer_backup(&active)?;
        Ok(PreparedLayers {
            before,
            target: active,
            desired: desired.context("Missing active slot in paired backup")?,
            verification: Verification::Wire,
        })
    }

    /// Legacy backups restore only their normal records. Secondary actions are
    /// captured fresh and retained exactly; no secondary defaults are invented.
    pub fn prepare_layers_restore_normal(&mut self, backup: Snapshot) -> Result<PreparedLayers> {
        ensure!(
            backup.format == 1 && backup.buttons.len() == 12,
            "Invalid normal backup"
        );
        let active = self.read_layers(Some(backup.slot))?;
        Self::layer_write_scope(&active)?;
        ensure!(
            !backup.device.serial.is_empty()
                && backup.device.serial == active.normal.device.serial
                && backup.device.product == active.normal.device.product,
            "Backup belongs to another mouse or connection"
        );
        let mut desired = active.clone();
        let mut grid = BTreeSet::new();
        for button in backup.buttons {
            ensure!(
                (1..=12).contains(&button.button) && grid.insert(button.button),
                "Invalid normal backup grid"
            );
            button.record()?;
            let id = button.button;
            *desired
                .normal
                .buttons
                .iter_mut()
                .find(|b| b.button == id)
                .unwrap() = button;
        }
        let mut seen = BTreeSet::new();
        for button in backup.controls {
            ensure!(
                (13..=16).contains(&button.button) && seen.insert(button.button),
                "Invalid normal backup control"
            );
            button.record()?;
            let id = button.button;
            *desired
                .normal
                .controls
                .iter_mut()
                .find(|b| b.button == id)
                .unwrap() = button;
        }
        let changed: Vec<_> = records(&active, 0)
            .zip(records(&desired, 0))
            .filter_map(|(a, b)| (a != b).then_some(b.button))
            .collect();
        for button in changed {
            desired
                .normal_echoes
                .iter_mut()
                .find(|e| e.button == button)
                .unwrap()
                .layer = 0;
            desired
                .hypershift
                .echoes
                .iter_mut()
                .find(|e| e.button == button)
                .unwrap()
                .layer = 0;
        }
        let before = self.capture_layer_backup(&active)?;
        Ok(PreparedLayers {
            before,
            target: active,
            desired,
            verification: Verification::Wire,
        })
    }

    fn write_layer_record(&mut self, slot: u8, layer: u8, button: &Button) -> Result<()> {
        slot_valid(slot)?;
        ensure!(
            layer <= 1 && self.transport.identity().product == 0xa7,
            "Unsupported layer write scope"
        );
        let mut request = [0; 10];
        request[..3].copy_from_slice(&[slot, control_id(button.button)?, layer]);
        request[3..].copy_from_slice(&button.record()?);
        self.transport.exchange(2, 0x0c, &request, 0)?;
        Ok(())
    }

    fn verify_layer_result(&mut self, plan: &PreparedLayers) -> Result<LayerReadback> {
        let after = self.read_layers(Some(plan.target.normal.slot))?;
        let mut expected = plan.desired.clone();
        for layer in 0..=1 {
            for ((original, desired), actual) in records(&plan.target, layer)
                .zip(records(&plan.desired, layer))
                .zip(records(&after, layer))
            {
                let verification = if original.record()? == desired.record()? {
                    Verification::Wire
                } else {
                    plan.verification
                };
                ensure!(
                    verification.matches(actual, desired)?,
                    "Layer {layer}, button {} readback mismatch",
                    desired.button
                );
            }
        }
        // Substitute only records already checked above to compare all metadata.
        expected.normal.buttons = after.normal.buttons.clone();
        expected.normal.controls = after.normal.controls.clone();
        expected.hypershift.buttons = after.hypershift.buttons.clone();
        expected.hypershift.controls = after.hypershift.controls.clone();
        ensure!(
            after == expected,
            "Layer transaction changed tracked device state"
        );
        for saved in &plan.before.slots {
            if saved.state.normal.slot != after.normal.slot {
                ensure!(
                    self.read_layers(Some(saved.state.normal.slot))? == saved.state,
                    "Layer transaction changed another slot"
                );
            }
            ensure!(
                self.get_button(saved.state.normal.slot, 3, 3)? == saved.middle,
                "Layer transaction changed middle click"
            );
        }
        Ok(after)
    }

    /// Caller must fsync backup() before acknowledging this commit. This API is
    /// exposed through the prepared session token; the controlled client persists
    /// its recovery backup before sending that token.
    pub fn commit_layers(&mut self, plan: PreparedLayers) -> Result<LayerReadback> {
        self.check_layer_backup(&plan.before)?;
        let mut attempted = Vec::new();
        let result = (|| -> Result<LayerReadback> {
            // Secondary first; install the normal-bank trigger last.
            for layer in [1, 0] {
                for (original, desired) in
                    records(&plan.target, layer).zip(records(&plan.desired, layer))
                {
                    if original.record()? == desired.record()? {
                        continue;
                    }
                    attempted.push((layer, original.clone())); // Includes lost acknowledgements.
                    self.write_layer_record(plan.target.normal.slot, layer, desired)?;
                    // Check the changed record immediately, then both banks and
                    // every untouched slot at the transaction boundary.
                    let actual = if layer == 0 {
                        self.get_button(
                            plan.target.normal.slot,
                            control_id(desired.button)?,
                            desired.button,
                        )?
                    } else {
                        let read = self.read_layers(Some(plan.target.normal.slot))?;
                        records(&read, 1)
                            .find(|b| b.button == desired.button)
                            .unwrap()
                            .clone()
                    };
                    ensure!(
                        plan.verification.matches(&actual, desired)?,
                        "Layer write did not read back"
                    );
                }
            }
            if matches!(plan.verification, Verification::Wire) {
                self.finish_layer_echoes(&plan, &mut attempted)?;
            }
            self.verify_layer_result(&plan)
        })();
        match result {
            Ok(after) => Ok(after),
            Err(error) => {
                if attempted.is_empty() {
                    return Err(error);
                }
                let recovery =
                    self.recover_layers(&plan.before, &attempted, plan.target.normal.slot);
                recovery.with_context(|| format!("Layer save failed ({error:#}); exact rollback could not be verified. Keep the paired backup"))?;
                bail!(
                    "Layer save failed: {error:#}. Original paired-bank records restored and verified."
                )
            }
        }
    }

    fn finish_layer_echoes(
        &mut self,
        plan: &PreparedLayers,
        attempted: &mut Vec<(u8, Button)>,
    ) -> Result<()> {
        let fresh = self.read_layers(Some(plan.target.normal.slot))?;
        for button in 1..=16 {
            let wanted_normal = plan.desired.normal_echo(button);
            let wanted_secondary = plan
                .desired
                .hypershift
                .echoes
                .iter()
                .find(|e| e.button == button)
                .unwrap()
                .layer;
            let current_secondary = fresh
                .hypershift
                .echoes
                .iter()
                .find(|e| e.button == button)
                .unwrap()
                .layer;
            if fresh.normal_echo(button) == wanted_normal && current_secondary == wanted_secondary {
                continue;
            }
            let original_secondary = plan
                .target
                .hypershift
                .echoes
                .iter()
                .find(|e| e.button == button)
                .unwrap()
                .layer;
            let changed = (0..=1).any(|layer| {
                let before = records(&plan.target, layer)
                    .find(|b| b.button == button)
                    .unwrap();
                let desired = records(&plan.desired, layer)
                    .find(|b| b.button == button)
                    .unwrap();
                before != desired
            }) || plan.target.normal_echo(button) != wanted_normal
                || original_secondary != wanted_secondary;
            ensure!(
                changed,
                "Unchanged control {button} echo changed unexpectedly"
            );
            ensure!(
                wanted_normal == wanted_secondary,
                "Cannot restore inconsistent original selector metadata"
            );
            let layer = wanted_normal;
            let original = records(&plan.target, layer)
                .find(|b| b.button == button)
                .unwrap();
            let desired = records(&plan.desired, layer)
                .find(|b| b.button == button)
                .unwrap();
            attempted.push((layer, original.clone()));
            self.write_layer_record(plan.target.normal.slot, layer, desired)?;
        }
        Ok(())
    }

    fn recover_layers(
        &mut self,
        before: &LayerBackup,
        attempted: &[(u8, Button)],
        target_slot: u8,
    ) -> Result<()> {
        ensure!(
            crate::faceplate::read(self)?.buttons == Some(12),
            "Faceplate changed; recovery stopped"
        );
        // Restore secondary before normal. If a layer-1 setter unexpectedly
        // aliases normal, the final normal pass repairs that collateral change.
        // Read all slots to detect collateral writes, but never write a primary.
        for layer in [1, 0] {
            for saved in &before.slots {
                let slot = saved.state.normal.slot;
                let fresh = self.read_layers(Some(slot));
                for original in records(&saved.state, layer) {
                    let changed = match &fresh {
                        Ok(read) => {
                            records(read, layer)
                                .find(|b| b.button == original.button)
                                .context("Missing recovery record")?
                                .record()?
                                != original.record()?
                        }
                        Err(_) => {
                            slot == target_slot
                                && attempted
                                    .iter()
                                    .any(|(bank, b)| *bank == layer && b.button == original.button)
                        }
                    };
                    if changed {
                        // A lost recovery acknowledgement can still have landed;
                        // continue recovery and let the final full read decide.
                        let _ = self.write_layer_record(slot, layer, original);
                    }
                }
            }
        }
        // Action restoration alone may leave both replies tagged with the last
        // secondary write. Restore the saved tag with its original bank record.
        for saved in &before.slots {
            let fresh = self.read_layers(Some(saved.state.normal.slot))?;
            for button in 1..=16 {
                let wanted = saved.state.normal_echo(button);
                let secondary = saved
                    .state
                    .hypershift
                    .echoes
                    .iter()
                    .find(|e| e.button == button)
                    .unwrap()
                    .layer;
                let actual_secondary = fresh
                    .hypershift
                    .echoes
                    .iter()
                    .find(|e| e.button == button)
                    .unwrap()
                    .layer;
                if fresh.normal_echo(button) == wanted && actual_secondary == secondary {
                    continue;
                }
                ensure!(
                    wanted == secondary,
                    "Cannot restore inconsistent original echoes"
                );
                let original = records(&saved.state, wanted)
                    .find(|b| b.button == button)
                    .unwrap();
                let _ = self.write_layer_record(saved.state.normal.slot, wanted, original);
            }
        }
        self.check_layer_backup(before)
            .context("Exact paired-bank recovery check failed")
    }
}
