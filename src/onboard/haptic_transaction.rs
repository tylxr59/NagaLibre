//! HyperScroll transactions are separate from mapping saves and binding defaults.
use super::{
    haptic::{Guard, Inspection, State},
    layer_transaction::LayerBackup,
    *,
};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Backup {
    pub format: u8,
    pub kind: String,
    pub guard: Guard,
    pub mappings: LayerBackup,
    pub slots: Vec<State>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Edit {
    pub active_position: u8,
    pub stages: Vec<u8>,
}

pub struct Prepared {
    pub backup: Backup,
    pub slot: u8,
    pub edit: Edit,
    // Only explicit backup restoration supplies original stage wire bytes.
    stage_wire: Option<Vec<u8>>,
}

fn validate_edit(edit: &Edit) -> Result<()> {
    ensure!(
        !edit.stages.is_empty()
            && edit.stages.len() <= 6
            && edit.stages.iter().all(|s| (0x81..=0x86).contains(s))
            && edit.stages.iter().collect::<BTreeSet<_>>().len() == edit.stages.len()
            && edit.active_position >= 1
            && usize::from(edit.active_position) <= edit.stages.len(),
        "Choose one to six distinct supported stages and an active list position"
    );
    Ok(())
}

fn stages_record(state: &State) -> Result<Vec<u8>> {
    ensure!(state.stages.len() <= 10, "Too many backed-up wheel stages");
    let record = state
        .records
        .iter()
        .find(|r| r.command == 0x87)
        .context("Missing stage-list wire record")?;
    ensure!(
        record.response.len() == 13
            && record.response[0] == state.slot
            && record.response[1] == state.active_position
            && usize::from(record.response[2]) == state.stages.len()
            && record.response[3..3 + state.stages.len()] == state.stages,
        "Inconsistent stage-list backup"
    );
    Ok(record.response.clone())
}

impl<T: Transport> Mouse<T> {
    pub fn prepare_haptic_restore(&mut self, mut backup: Backup, slot: u8) -> Result<Prepared> {
        ensure!(
            backup.format == 1
                && backup.kind == "haptic_settings_backup"
                && backup.slots.iter().map(|s| s.slot).collect::<Vec<_>>() == backup.guard.slots,
            "Not a complete wheel settings backup"
        );
        let fresh = self.inspect_haptic(Some(slot))?;
        // A reconnect may change hidraw path; persisted identity is serial/PID.
        backup.guard.device.path = fresh.guard.device.path.clone();
        ensure!(
            backup.guard == fresh.guard,
            "Backup belongs to different device state"
        );
        for entry in &mut backup.mappings.slots {
            entry.state.normal.device.path = fresh.guard.device.path.clone();
        }
        self.check_layer_backup(&backup.mappings)?;
        let original = backup
            .slots
            .iter()
            .find(|s| s.slot == slot)
            .context("Backup lacks selected slot")?;
        let edit = Edit {
            active_position: original.active_position,
            stages: original.stages.clone(),
        };
        validate_edit(&edit)?;
        stages_record(original)?;
        // This restoration path restores stage selection/order only. It must
        // never claim to recover unrelated custom wheel changes.
        for before in &backup.slots {
            let mut current = self.inspect_haptic(Some(before.slot))?.state;
            if before.slot == slot {
                current.stages = before.stages.clone();
                current.active_position = before.active_position;
                for record in &mut current.records {
                    if [0x80, 0x87].contains(&record.command) {
                        *record = before
                            .records
                            .iter()
                            .find(|r| r.command == record.command)
                            .context("Missing original stage reply")?
                            .clone();
                    }
                }
            }
            ensure!(
                current == *before,
                "Unrelated wheel settings differ; stage-only restoration refused"
            );
        }
        let wire = stages_record(original)?;
        let mut plan = self.prepare_haptic(&fresh, edit)?;
        plan.stage_wire = Some(wire);
        Ok(plan)
    }

    pub fn prepare_haptic(&mut self, known: &Inspection, edit: Edit) -> Result<Prepared> {
        validate_edit(&edit)?;
        ensure!(
            known.format == 1 && known.kind == "haptic_diagnostic",
            "Read the wheel before editing"
        );
        ensure!(
            known.state.slot == known.guard.active
                && !known.state.records.iter().any(|r| r.rejection.is_some()),
            "Wheel saves currently require the active slot with readable metadata"
        );
        ensure!(
            self.inspect_haptic(Some(known.state.slot))? == *known,
            "Wheel snapshot is stale; read again"
        );
        let target = self.read_layers(None)?;
        let mappings = self.capture_layer_backup(&target)?;
        let mut slots = Vec::new();
        for slot in &known.guard.slots {
            let read = self.inspect_haptic(Some(*slot))?;
            ensure!(
                read.guard == known.guard,
                "Mouse changed while preparing wheel backup"
            );
            validate_edit(&Edit {
                active_position: read.state.active_position,
                stages: read.state.stages.clone(),
            })?;
            stages_record(&read.state)?;
            if *slot == known.state.slot {
                ensure!(
                    read.state == known.state,
                    "Wheel changed while preparing backup"
                );
            }
            slots.push(read.state);
        }
        let backup = Backup {
            format: 1,
            kind: "haptic_settings_backup".into(),
            guard: known.guard.clone(),
            mappings,
            slots,
        };
        self.check_haptic_backup(&backup)?;
        Ok(Prepared {
            backup,
            slot: known.state.slot,
            edit,
            stage_wire: None,
        })
    }

    pub(super) fn check_haptic_backup(&mut self, backup: &Backup) -> Result<()> {
        ensure!(
            backup.format == 1
                && backup.kind == "haptic_settings_backup"
                && backup.slots.iter().map(|s| s.slot).collect::<Vec<_>>() == backup.guard.slots,
            "Incomplete wheel-settings backup"
        );
        ensure!(
            self.haptic_guard()? == backup.guard,
            "Mouse changed; wheel backup is stale"
        );
        self.check_layer_backup(&backup.mappings)?;
        for state in &backup.slots {
            ensure!(
                self.inspect_haptic(Some(state.slot))?.state == *state,
                "Wheel state changed; read again"
            );
        }
        Ok(())
    }

    fn set_haptic_stages(
        &mut self,
        state: &State,
        edit: &Edit,
        original_wire: Option<&[u8]>,
    ) -> Result<()> {
        validate_edit(edit)?;
        if let Some(wire) = original_wire {
            ensure!(
                wire.len() == 13
                    && wire[0] == state.slot
                    && wire[1] == edit.active_position
                    && usize::from(wire[2]) == edit.stages.len()
                    && wire[3..3 + edit.stages.len()] == edit.stages,
                "Inconsistent wheel restoration record"
            );
            if wire != stages_record(state)? {
                self.transport.exchange(0x15, 7, wire, 0)?;
            }
            return Ok(());
        }
        if state.stages == edit.stages {
            if state.active_position != edit.active_position {
                self.transport
                    .exchange(0x15, 0, &[state.slot, edit.active_position], 0)?;
            }
        } else {
            // The native 15/07 setter zero-initializes its ten-entry array and
            // copies only the enabled count. Old entries beyond that count are
            // obsolete preset IDs, not opaque bytes to retain on a draft save.
            let mut wire = vec![0; 13];
            wire[0] = state.slot;
            wire[1] = edit.active_position;
            wire[2] = edit.stages.len() as u8;
            wire[3..3 + edit.stages.len()].copy_from_slice(&edit.stages);
            self.transport.exchange(0x15, 7, &wire, 0)?;
        }
        Ok(())
    }

    fn check_haptic_result(&mut self, plan: &Prepared) -> Result<Inspection> {
        ensure!(
            self.haptic_guard()? == plan.backup.guard,
            "Mouse changed during wheel save"
        );
        self.check_layer_backup(&plan.backup.mappings)?;
        let mut target = None;
        for before in &plan.backup.slots {
            let after = self.inspect_haptic(Some(before.slot))?;
            if before.slot != plan.slot {
                ensure!(
                    after.state == *before,
                    "Another slot's wheel settings changed"
                );
                continue;
            }
            ensure!(
                after.state.stages == plan.edit.stages
                    && after.state.active_position == plan.edit.active_position,
                "Wheel stages did not read back"
            );
            if let Some(wire) = &plan.stage_wire {
                ensure!(
                    stages_record(&after.state)? == *wire,
                    "Original wheel stage record did not restore exactly"
                );
            }
            let mut comparable = after.state.clone();
            comparable.stages = before.stages.clone();
            comparable.active_position = before.active_position;
            // Only the stage-list and active-position replies are allowed to
            // differ for these edits. Preserve every unrelated raw payload.
            for record in &mut comparable.records {
                if [0x80, 0x87].contains(&record.command) {
                    *record = before
                        .records
                        .iter()
                        .find(|r| r.command == record.command)
                        .context("Missing original stage record")?
                        .clone();
                }
            }
            ensure!(comparable == *before, "Unrelated wheel state changed");
            target = Some(after);
        }
        target.context("Target slot missing from wheel backup")
    }

    pub fn commit_haptic(&mut self, plan: Prepared) -> Result<Inspection> {
        validate_edit(&plan.edit)?;
        self.check_haptic_backup(&plan.backup)?;
        let before = plan
            .backup
            .slots
            .iter()
            .find(|s| s.slot == plan.slot)
            .context("Missing target wheel state")?;
        let changed = before.stages != plan.edit.stages
            || before.active_position != plan.edit.active_position
            || plan
                .stage_wire
                .as_ref()
                .is_some_and(|wire| stages_record(before).is_ok_and(|current| current != *wire));
        let result = (|| {
            self.set_haptic_stages(before, &plan.edit, plan.stage_wire.as_deref())?;
            self.check_haptic_result(&plan)
        })();
        match result {
            Ok(after) => Ok(after),
            Err(error) if changed => {
                // Marking a write attempted precedes exchange: a lost ack may
                // mean the setting landed. Always attempt exact restoration.
                let rollback = (|| -> Result<()> {
                    ensure!(
                        self.haptic_guard()? == plan.backup.guard,
                        "Mouse changed; cannot restore safely"
                    );
                    self.check_layer_backup(&plan.backup.mappings)?;
                    let wire = stages_record(before)?;
                    let ack = self.transport.exchange(0x15, 7, &wire, 0);
                    // Verification runs even if the restoration ack was lost.
                    let verified = self.check_haptic_backup(&plan.backup);
                    if verified.is_ok() {
                        return Ok(());
                    }
                    ack?;
                    verified
                })();
                match rollback {
                    Ok(()) => bail!(
                        "Wheel save failed: {error:#}. Original wheel settings restored exactly."
                    ),
                    Err(restore) => bail!(
                        "Wheel save failed: {error:#}. RESTORATION INCOMPLETE: {restore:#}. Keep the prepared wheel backup for recovery."
                    ),
                }
            }
            Err(error) => Err(error),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    struct Fake {
        stages: BTreeMap<u8, Vec<u8>>,
        writes: Vec<(u8, Vec<u8>)>,
        lost: usize,
        refuse_restore: bool,
        alter_other: bool,
        metadata_tail: u8,
    }
    impl Fake {
        fn new() -> Self {
            let mut wire = vec![1, 5, 5, 0x81, 0x82, 0x83, 0x84, 0x85];
            wire.resize(13, 0);
            let mut second = wire.clone();
            second[0] = 2;
            Self {
                stages: BTreeMap::from([(1, wire), (2, second)]),
                writes: vec![],
                lost: 0,
                refuse_restore: false,
                alter_other: false,
                metadata_tail: 0xa5,
            }
        }
    }
    impl Transport for Fake {
        fn identity(&self) -> Identity {
            Identity {
                path: "mock".into(),
                product: 0xa7,
                serial: String::new(),
            }
        }
        fn exchange(&mut self, class: u8, command: u8, p: &[u8], _: usize) -> Result<Vec<u8>> {
            Ok(match (class, command) {
                (0, 0x82) => {
                    let mut s = vec![0; 22];
                    s[..4].copy_from_slice(b"TEST");
                    s
                }
                (0, 0x84) => vec![0, 0],
                (5, 0x81) => vec![5, 1, 2],
                (5, 0x84) => vec![1, 0, 0, 0, 0, 0],
                (0, 0xb9) => vec![3],
                (2, 0x8c) => {
                    let mut r = p.to_vec();
                    r[3..].fill(0);
                    if p[1] <= 3 {
                        r[3..6].copy_from_slice(&[1, 1, p[1]]);
                    } else {
                        r[3..].copy_from_slice(&[2, 1, 0, 0x1e, 0xde, 0xad, 0xa5]);
                    }
                    r
                }
                (0x15, 0x80) => vec![p[0], self.stages[&p[0]][1]],
                (0x15, 0x87) => self.stages[&p[0]].clone(),
                (0x15, 0x88) => vec![0],
                (0x15, 0x85) => vec![0, 80, 0, 80, 0, 80],
                (0x15, 0x83) => {
                    let mut r = p.to_vec();
                    r[2] = 1;
                    r[3] = 1;
                    r
                }
                (0x15, 0x89) => {
                    let mut r = vec![p[0], 40];
                    r.resize(66, self.metadata_tail);
                    r
                }
                (0x15, 0 | 7) => {
                    self.writes.push((command, p.to_vec()));
                    if self.refuse_restore && self.writes.len() > 1 {
                        bail!("Restore rejected");
                    }
                    if command == 0 {
                        self.stages.get_mut(&p[0]).unwrap()[1] = p[1];
                    } else {
                        *self.stages.get_mut(&p[0]).unwrap() = p.to_vec();
                    }
                    if self.alter_other {
                        self.stages.get_mut(&2).unwrap()[1] = 2;
                    }
                    if self.lost > 0 {
                        self.lost -= 1;
                        bail!("Accepted; acknowledgement lost");
                    }
                    p.to_vec()
                }
                _ => bail!("Unexpected command {class:02x}/{command:02x}"),
            })
        }
    }
    fn mouse() -> Mouse<Fake> {
        Mouse {
            transport: Fake::new(),
        }
    }
    fn edit() -> Edit {
        Edit {
            active_position: 1,
            stages: vec![0x81, 0x82, 0x83, 0x84, 0x85],
        }
    }
    #[test]
    fn active_selection_writes_only_one_haptic_record_and_preserves_all_other_state() {
        let mut m = mouse();
        let before = m.inspect_haptic(None).unwrap();
        let p = m.prepare_haptic(&before, edit()).unwrap();
        assert_eq!(p.backup.slots.len(), 2);
        assert_eq!(p.backup.mappings.slots.len(), 2);
        let after = m.commit_haptic(p).unwrap();
        assert_eq!(after.state.active_position, 1);
        assert_eq!(m.transport.writes, vec![(0, vec![1, 1])]);
    }
    #[test]
    fn unchanged_save_skips_writes_and_stale_wire_tail_prevents_commit() {
        let mut m = mouse();
        let before = m.inspect_haptic(None).unwrap();
        let p = m
            .prepare_haptic(
                &before,
                Edit {
                    active_position: 5,
                    ..edit()
                },
            )
            .unwrap();
        m.commit_haptic(p).unwrap();
        assert!(m.transport.writes.is_empty());
        let p = m.prepare_haptic(&before, edit()).unwrap();
        m.transport.metadata_tail ^= 1;
        assert!(m.commit_haptic(p).is_err());
        assert!(m.transport.writes.is_empty());
    }
    #[test]
    fn lost_write_and_restore_acknowledgements_still_verify_exact_original() {
        for lost in [1, 2] {
            let mut m = mouse();
            let before = m.inspect_haptic(None).unwrap();
            let p = m.prepare_haptic(&before, edit()).unwrap();
            m.transport.lost = lost;
            let error = m.commit_haptic(p).unwrap_err().to_string();
            assert!(error.contains("restored exactly"), "{error}");
            assert_eq!(m.inspect_haptic(None).unwrap(), before);
            assert_eq!(m.transport.writes.len(), 2);
        }
    }
    #[test]
    fn partial_restore_and_other_slot_changes_never_report_success() {
        for other in [false, true] {
            let mut m = mouse();
            let before = m.inspect_haptic(None).unwrap();
            let p = m.prepare_haptic(&before, edit()).unwrap();
            m.transport.lost = 1;
            m.transport.refuse_restore = !other;
            m.transport.alter_other = other;
            let error = m.commit_haptic(p).unwrap_err().to_string();
            assert!(error.contains("RESTORATION INCOMPLETE"), "{error}");
        }
    }
    #[test]
    fn stage_order_backup_restore_is_exact_and_diagnostic_cannot_restore() {
        let mut m = mouse();
        let before = m.inspect_haptic(None).unwrap();
        let mut e = edit();
        e.stages.reverse();
        let p = m.prepare_haptic(&before, e).unwrap();
        let backup = p.backup.clone();
        m.commit_haptic(p).unwrap();
        let p = m.prepare_haptic_restore(backup, 1).unwrap();
        m.commit_haptic(p).unwrap();
        assert_eq!(m.inspect_haptic(None).unwrap(), before);
        assert!(serde_json::from_value::<Backup>(serde_json::to_value(before).unwrap()).is_err());
    }
    #[test]
    fn two_stage_cycle_and_shortened_list_restore_original_after_manual_cycling_or_lost_ack() {
        for lost_ack in [false, true] {
            let mut m = mouse();
            // Restoration must preserve even a nonstandard unused entry; a
            // normal shortened-list save follows the native zero padding.
            m.transport.stages.get_mut(&1).unwrap()[12] = 0xa5;
            let before = m.inspect_haptic(None).unwrap();
            let plan = m
                .prepare_haptic(
                    &before,
                    Edit {
                        active_position: 2,
                        stages: vec![0x85, 0x81],
                    },
                )
                .unwrap();
            let backup = plan.backup.clone();
            if lost_ack {
                m.transport.lost = 1;
                assert!(
                    m.commit_haptic(plan)
                        .unwrap_err()
                        .to_string()
                        .contains("restored exactly")
                );
            } else {
                let after = m.commit_haptic(plan).unwrap();
                assert_eq!(after.state.stages, vec![0x85, 0x81]);
                assert_eq!(after.state.active_position, 2);
                // User presses the firmware cycling button while the helper
                // is stopped. Restoration must use fresh state and recover the
                // original five-stage list, not assume the applied position.
                m.transport.stages.get_mut(&1).unwrap()[1] = 1;
                let restore = m.prepare_haptic_restore(backup, 1).unwrap();
                m.commit_haptic(restore).unwrap();
            }
            assert_eq!(m.inspect_haptic(None).unwrap(), before);
            assert_eq!(&m.transport.writes[0].1[..5], &[1, 2, 2, 0x85, 0x81]);
            assert_eq!(&m.transport.writes[0].1[5..], &[0; 8]);
            assert_eq!(m.transport.writes.last().unwrap().1[12], 0xa5);
            assert!(m.transport.writes.iter().all(|(command, _)| *command == 7));
        }
    }
    #[test]
    fn invalid_stage_lists_are_rejected_without_hardware_access() {
        let mut m = mouse();
        let before = m.inspect_haptic(None).unwrap();
        for stages in [vec![], vec![0x81, 0x81], vec![0xff]] {
            assert!(
                m.prepare_haptic(
                    &before,
                    Edit {
                        active_position: 1,
                        stages
                    }
                )
                .is_err()
            );
        }
        assert!(m.transport.writes.is_empty());
    }
}
