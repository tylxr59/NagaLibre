//! One native-framed, idempotent custom-table replay with exact-state recovery.
//! This diagnostic cannot generate a new curve, change its length or enable Custom.
use super::{haptic::State, haptic_transaction::Backup, *};
use serde_json::{Value, json};
use std::{
    fs::{File, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::Path,
};

pub(super) fn target(backup: &Backup) -> Result<&State> {
    let guard = &backup.guard;
    ensure!(
        backup.format == 1
            && backup.kind == "haptic_settings_backup"
            && guard.device.product == 0xa7
            && !guard.device.serial.is_empty()
            && guard.mode == [0, 0]
            && guard.module_id == 3
            && guard.slots.contains(&guard.active)
            && guard.slots.iter().collect::<BTreeSet<_>>().len() == guard.slots.len()
            && backup.slots.iter().map(|s| s.slot).collect::<Vec<_>>() == guard.slots
            && backup.mappings.format == 1
            && backup.mappings.kind == "paired_mapping_backup"
            && backup
                .mappings
                .slots
                .iter()
                .map(|s| s.state.normal.slot)
                .collect::<Vec<_>>()
                == guard.slots,
        "Probe requires a complete wired active-slot wheel/mapping checkpoint"
    );
    for entry in &backup.mappings.slots {
        super::layer_transaction::validate_state(&entry.state)?;
        let normal = &entry.state.normal;
        ensure!(
            normal.device == guard.device
                && normal.slots == guard.slots
                && normal.active == guard.active
                && normal.mode == guard.mode
                && normal.slot_capacity == Some(guard.capacity),
            "Inconsistent mapping checkpoint"
        );
    }
    let state = backup
        .slots
        .iter()
        .find(|s| s.slot == guard.active)
        .context("Missing active wheel slot")?;
    ensure!(
        state.active_position > 0
            && state.stages.get(usize::from(state.active_position) - 1) == Some(&0x85)
            && !state.stages.contains(&0x86)
            && state.configuration.len() == 26
            && state.configuration[..4] == [state.slot, 6, 1, 1]
            && state.tables.len() == 3
            && state.tables[0].len() >= 8
            && !state.records.iter().any(|r| r.rejection.is_some())
            && state.metadata.len() == 40,
        "Initial replay requires Smooth Scroll active, Custom disabled, and a complete known custom format"
    );
    Ok(state)
}

fn packet(state: &State) -> Vec<u8> {
    // Device167 +568: declared length = 10 + 8*n, while the fields/points
    // occupy 7 + 8*n. Retain native length, deterministically zero the extra
    // three bytes, and never copy native stack padding/security-cookie bytes.
    let mut bytes = vec![0; 74];
    bytes[..7].copy_from_slice(&[state.slot, 6, 1, 0, 0, 0, 8]);
    for (index, point) in state.tables[0][..8].iter().enumerate() {
        bytes[7 + index * 8..15 + index * 8].copy_from_slice(point);
    }
    bytes
}

pub(super) fn checkpoint(file: &mut File, stage: &str, details: Value) -> Result<()> {
    serde_json::to_writer(&mut *file, &json!({"stage":stage,"details":details}))?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

// Mask only the bytes this probe could have changed, before float decoding.
// Actual replies are retained in the private journal. Final verification uses
// the original transport without this wrapper.
struct RecoveryRead<'a, T> {
    inner: &'a mut T,
    slot: u8,
    points: &'a [[u8; 8]],
    observed: Vec<Vec<u8>>,
}
impl<T: Transport> Transport for RecoveryRead<'_, T> {
    fn identity(&self) -> Identity {
        self.inner.identity()
    }
    fn exchange(&mut self, class: u8, command: u8, p: &[u8], echo: usize) -> Result<Vec<u8>> {
        let mut reply = self.inner.exchange(class, command, p, echo)?;
        if class == 0x15 && command == 0x84 && p.get(..7) == Some(&[self.slot, 6, 1, 0, 0, 0, 8]) {
            ensure!(
                reply.len() == 71 && reply[..7] == p[..7],
                "Unexpected recovery table header"
            );
            self.observed.push(reply.clone());
            for (i, point) in self.points.iter().enumerate() {
                reply[7 + i * 8..15 + i * 8].copy_from_slice(point);
            }
        }
        Ok(reply)
    }
}

impl<T: Transport> Mouse<T> {
    fn check_haptic_probe_recovery(&mut self, backup: &Backup) -> Result<Value> {
        let original = target(backup)?;
        let mut reader = Mouse {
            transport: RecoveryRead {
                inner: &mut self.transport,
                slot: original.slot,
                points: &original.tables[0][..8],
                observed: Vec::new(),
            },
        };
        ensure!(
            reader.haptic_guard()? == backup.guard,
            "Mouse changed; table replay recovery stopped"
        );
        reader.check_layer_backup(&backup.mappings)?;
        for before in &backup.slots {
            ensure!(
                reader.inspect_haptic(Some(before.slot))?.state == *before,
                "Unrelated wheel state changed; replay recovery refused"
            );
        }
        ensure!(
            reader.haptic_guard()? == backup.guard,
            "Mouse changed during replay recovery checks"
        );
        Ok(json!({"observed_target_replies":reader.transport.observed}))
    }

    pub fn probe_haptic_table(
        &mut self,
        backup: &Backup,
        journal: &Path,
        restore_only: bool,
    ) -> Result<Value> {
        let original = target(backup)?;
        let payload = packet(original);
        let journal_backup = backup;
        let mut normalized = backup.clone();
        if restore_only {
            let current = self.haptic_guard()?;
            normalized.guard.device.path = current.device.path.clone();
            for entry in &mut normalized.mappings.slots {
                entry.state.normal.device.path = current.device.path.clone();
            }
            ensure!(
                current == normalized.guard,
                "Device/state changed; recovery refused"
            );
        }
        let backup = &normalized;
        let mut file = if restore_only {
            let mut file = OpenOptions::new()
                .read(true)
                .append(true)
                .custom_flags(libc::O_NOFOLLOW)
                .open(journal)?;
            let metadata = file.metadata()?;
            ensure!(
                metadata.is_file()
                    && metadata.len() <= 8 * 1024 * 1024
                    && metadata.permissions().mode() & 0o077 == 0
                    && metadata.uid() == {
                        // SAFETY: geteuid has no arguments or memory preconditions.
                        unsafe { libc::geteuid() }
                    },
                "Invalid private helper journal"
            );
            let mut text = String::new();
            file.read_to_string(&mut text)?;
            let first: Value =
                serde_json::from_str(text.lines().next().context("Empty helper journal")?)?;
            ensure!(
                first["stage"] == "table_replay_pending"
                    && first["details"]["backup"] == json!(journal_backup)
                    && first["details"]["payload"] == json!(payload),
                "Helper journal does not match original replay"
            );
            let finished = text
                .lines()
                .filter_map(|line| serde_json::from_str::<Value>(line).ok())
                .any(|record| {
                    record["stage"] == "finished" && record["details"]["restored_exactly"] == true
                });
            ensure!(
                !finished,
                "This replay is already restored; do not repeat it"
            );
            self.check_haptic_probe_recovery(backup)?;
            // An interrupted journal append may lack its last newline.
            file.write_all(b"\n")?;
            file.sync_all()?;
            file
        } else {
            self.check_haptic_backup(backup)?;
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .custom_flags(libc::O_NOFOLLOW)
                .open(journal)?;
            let parent = journal
                .parent()
                .filter(|p| !p.as_os_str().is_empty())
                .unwrap_or(Path::new("."));
            File::open(parent)?.sync_all()?;
            checkpoint(
                &mut file,
                "table_replay_pending",
                json!({"backup":backup,"payload":payload}),
            )?;
            // No mutation precedes the create-new, fsynced journal and recheck.
            self.check_haptic_backup(backup)?;
            file
        };
        let probe = if restore_only {
            None
        } else {
            // One attempt only: a lost acknowledgement may mean it landed.
            let acknowledged = self.transport.exchange(0x15, 4, &payload, 0);
            let checked = self.check_haptic_backup(backup);
            Some((acknowledged, checked))
        };
        // Journal failure must not prevent attempting recovery after a write.
        let journal_error = checkpoint(
            &mut file,
            "original_chunk_restore_pending",
            json!({"restore_only":restore_only}),
        )
        .err();
        let recovery = (|| -> Result<Value> {
            let observed = self.check_haptic_probe_recovery(backup)?;
            let evidence_error = checkpoint(&mut file, "recovery_guard", observed)
                .err()
                .map(|e| format!("{e:#}"));
            let acknowledged = self.transport.exchange(0x15, 4, &payload, 0);
            let checked = self.check_haptic_backup(backup);
            let acknowledgement_error = acknowledged.err().map(|e| format!("{e:#}"));
            checked.context("Full captured-state verification after replay restoration failed")?;
            Ok(
                json!({"restored_exactly":true,"restore_acknowledgement_error":acknowledgement_error,"recovery_evidence_error":evidence_error}),
            )
        })();
        let mut report = json!({"format":1,"kind":"haptic_table_replay_result","restore_only":restore_only,
            "declared_payload_length":74,"point_count":8,"table_selector":1,
            "restored_exactly":recovery.is_ok(),"probe_passed":false,
            "journal_checkpoint_error":journal_error.map(|e|format!("{e:#}"))});
        if let Some((acknowledged, checked)) = probe {
            report["probe_passed"] =
                json!(acknowledged.is_ok() && checked.is_ok() && recovery.is_ok());
            report["probe_acknowledgement_error"] =
                json!(acknowledged.err().map(|e| format!("{e:#}")));
            report["probe_verification_error"] = json!(checked.err().map(|e| format!("{e:#}")));
        }
        match recovery {
            Ok(details) => report["recovery"] = details,
            Err(error) => report["recovery_error"] = json!(format!("{error:#}")),
        }
        let logged = checkpoint(&mut file, "finished", report.clone());
        ensure!(
            report["restored_exactly"] == true,
            "TABLE REPLAY RESTORATION INCOMPLETE: {}",
            report["recovery_error"]
        );
        logged.context(
            "Original state verified but helper completion journal could not be fsynced",
        )?;
        Ok(report)
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
        points: Vec<[u8; 8]>,
        corrupt: bool,
        path: String,
    }
    impl Fake {
        fn new() -> Self {
            let mut wire = vec![1, 5, 5, 0x81, 0x82, 0x83, 0x84, 0x85];
            wire.resize(13, 0);
            let mut second = wire.clone();
            second[0] = 2;
            Self {
                points: (0u8..9)
                    .map(|n| {
                        let mut p = [0; 8];
                        p[..4].copy_from_slice(&f32::from(n).to_le_bytes());
                        p
                    })
                    .collect(),
                corrupt: false,
                path: "mock".into(),
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
                path: self.path.clone(),
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
                    r[21] = 9;
                    r
                }
                (0x15, 0x89) => {
                    let mut r = vec![p[0], 40];
                    r.resize(66, self.metadata_tail);
                    r
                }
                (0x15, 0x84) => {
                    let mut r = p.to_vec();
                    let start = usize::from(u16::from_be_bytes([p[3], p[4]]));
                    let count = usize::from(u16::from_be_bytes([p[5], p[6]]));
                    for i in 0..count {
                        let point = if p[0] == 1 {
                            self.points[start + i]
                        } else {
                            let mut point = [0; 8];
                            point[..4].copy_from_slice(&((start + i) as f32).to_le_bytes());
                            point
                        };
                        r[7 + i * 8..15 + i * 8].copy_from_slice(&point);
                    }
                    r
                }
                (0x15, 4) => {
                    assert_eq!(p.len(), 74);
                    assert_eq!(&p[..7], &[1, 6, 1, 0, 0, 0, 8]);
                    assert_eq!(&p[71..], &[0, 0, 0]);
                    self.writes.push((command, p.to_vec()));
                    if self.refuse_restore && self.writes.len() > 1 {
                        bail!("Restore rejected");
                    }
                    for i in 0..8 {
                        self.points[i].copy_from_slice(&p[7 + i * 8..15 + i * 8]);
                    }
                    if self.corrupt && self.writes.len() == 1 {
                        self.points[0][..4].copy_from_slice(&f32::NAN.to_le_bytes());
                    }
                    if self.alter_other {
                        self.points[8][0] ^= 1;
                    }
                    if self.lost > 0 {
                        self.lost -= 1;
                        bail!("Accepted; acknowledgement lost");
                    }
                    vec![]
                }
                _ => bail!("Unexpected command {class:02x}/{command:02x}"),
            })
        }
    }

    struct Temp(std::path::PathBuf);
    impl Temp {
        fn new() -> Self {
            static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let path = std::env::temp_dir().join(format!(
                "nagalibre-probe-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
            ));
            std::fs::create_dir(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    fn setup() -> (Mouse<Fake>, Backup, Temp) {
        let mut m = Mouse {
            transport: Fake::new(),
        };
        let before = m.inspect_haptic(None).unwrap();
        let edit = super::super::haptic_transaction::Edit {
            active_position: 5,
            stages: before.state.stages.clone(),
        };
        let backup = m.prepare_haptic(&before, edit).unwrap().backup;
        (m, backup, Temp::new())
    }
    #[test]
    fn unchanged_replay_and_lost_acknowledgements_restore_exactly() {
        for lost in 0..=2 {
            let (mut m, b, t) = setup();
            m.transport.lost = lost;
            let r = m
                .probe_haptic_table(&b, &t.0.join("journal"), false)
                .unwrap();
            assert_eq!(r["restored_exactly"], true);
            assert_eq!(r["probe_passed"], lost == 0);
            assert_eq!(m.transport.writes.len(), 2);
            m.check_haptic_backup(&b).unwrap();
        }
    }
    #[test]
    fn damaged_nonfinite_target_is_restored_but_never_passes_probe() {
        let (mut m, b, t) = setup();
        m.transport.corrupt = true;
        let r = m
            .probe_haptic_table(&b, &t.0.join("journal"), false)
            .unwrap();
        assert_eq!(r["restored_exactly"], true);
        assert_eq!(r["probe_passed"], false);
        m.check_haptic_backup(&b).unwrap();
    }
    #[test]
    fn unrelated_change_or_refused_restore_is_incomplete() {
        for other in [false, true] {
            let (mut m, b, t) = setup();
            m.transport.corrupt = true;
            m.transport.refuse_restore = !other;
            m.transport.alter_other = other;
            let e = m
                .probe_haptic_table(&b, &t.0.join("journal"), false)
                .unwrap_err();
            assert!(e.to_string().contains("RESTORATION INCOMPLETE"));
            assert_eq!(m.transport.writes.len(), if other { 1 } else { 2 });
        }
    }
    #[test]
    fn stale_checkpoint_or_existing_journal_prevents_all_writes() {
        for stale in [false, true] {
            let (mut m, b, t) = setup();
            let path = t.0.join("journal");
            if stale {
                m.transport.metadata_tail ^= 1;
            } else {
                std::fs::write(&path, b"existing").unwrap();
            }
            assert!(m.probe_haptic_table(&b, &path, false).is_err());
            assert!(m.transport.writes.is_empty());
        }
    }
    #[test]
    fn interrupted_journal_restores_only_original_with_fresh_path() {
        let (mut m, b, t) = setup();
        let path = t.0.join("journal");
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&path)
            .unwrap();
        checkpoint(
            &mut file,
            "table_replay_pending",
            json!({"backup":b,"payload":packet(target(&b).unwrap())}),
        )
        .unwrap();
        m.transport.points[0][..4].copy_from_slice(&f32::NAN.to_le_bytes());
        m.transport.path = "reconnected".into();
        let r = m.probe_haptic_table(&b, &path, true).unwrap();
        assert_eq!(r["restored_exactly"], true);
        assert_eq!(r["probe_passed"], false);
        assert_eq!(m.transport.writes.len(), 1);
        assert!(m.probe_haptic_table(&b, &path, true).is_err());
        assert_eq!(m.transport.writes.len(), 1);
    }
}
