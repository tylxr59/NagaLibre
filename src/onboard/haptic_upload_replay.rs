//! Bounded full upload of original Custom settings, with a separate recovery pass.
//! No generated curves, metadata writes, stage selection, firmware or mapping writes.
use super::{
    haptic_probe::{checkpoint, target},
    haptic_transaction::Backup,
    *,
};
use serde_json::{Value, json};
use std::{
    fs::{File, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::Path,
};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Packet {
    command: u8,
    payload: Vec<u8>,
}

#[derive(Debug)]
struct UploadStep {
    index: usize,
    total: usize,
}
impl std::fmt::Display for UploadStep {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "Upload packet {}/{}; no individual packet retry",
            self.index + 1,
            self.total
        )
    }
}
impl std::error::Error for UploadStep {}

pub(super) fn packets_with_source(backup: &Backup, independent: bool) -> Result<Vec<Packet>> {
    let state = target(backup)?;
    ensure!(
        independent || !super::haptic_views::table_prefix_overlap(&state.tables),
        "Custom upload blocked: stored velocity replies overlap clockwise data; independent table backup/recovery is unverified"
    );
    let config = &state.configuration;
    ensure!(
        config[4..8] == [0; 4] && config[12..16] == [0; 4],
        "Initial full replay requires the captured zero-deadzone format"
    );
    let mut result = vec![Packet {
        command: 3,
        payload: config.clone(),
    }];
    for (table, points) in state.tables.iter().enumerate() {
        for point in points {
            super::haptic::finite(point)?;
        }
        let n = usize::from(u16::from_be_bytes([
            config[20 + table * 2],
            config[21 + table * 2],
        ]));
        ensure!(
            n == points.len() && (1..=80).contains(&n) && n <= usize::from(state.capacities[table]),
            "Full replay requires three nonempty original tables within capacity"
        );
        for (chunk, values) in points.chunks(8).enumerate() {
            // Native Device167 length = 10 + 8*n, including three zero extra
            // bytes. No alternative lengths or guessed padding are attempted.
            let mut payload = vec![0; 10 + values.len() * 8];
            payload[..3].copy_from_slice(&[state.slot, 6, table as u8 + 1]);
            payload[3..5].copy_from_slice(&((chunk * 8) as u16).to_be_bytes());
            payload[5..7].copy_from_slice(&(values.len() as u16).to_be_bytes());
            for (i, p) in values.iter().enumerate() {
                payload[7 + i * 8..15 + i * 8].copy_from_slice(p);
            }
            result.push(Packet {
                command: 4,
                payload,
            });
        }
    }
    Ok(result)
}

fn packets(backup: &Backup) -> Result<Vec<Packet>> {
    packets_with_source(backup, false)
}

impl<T: Transport> Mouse<T> {
    /// Do not decode partially staged custom data as a valid snapshot. Recovery
    /// is limited to the target configuration/tables; every other captured field
    /// and all other slots must still match, including exact mapping records.
    fn check_upload_recovery(&mut self, backup: &Backup) -> Result<()> {
        let active = target(backup)?;
        ensure!(
            self.haptic_guard()? == backup.guard,
            "Device/state changed; upload recovery refused"
        );
        self.check_layer_backup(&backup.mappings)?;
        for before in &backup.slots {
            if before.slot != active.slot {
                ensure!(
                    self.inspect_haptic(Some(before.slot))?.state == *before,
                    "Another slot changed; upload recovery refused"
                );
                continue;
            }
            for command in [0x80, 0x87, 0x88, 0x85, 0x89] {
                let record = before
                    .records
                    .iter()
                    .find(|r| r.command == command)
                    .context("Missing original non-custom record")?;
                ensure!(
                    record.rejection.is_none(),
                    "Missing original non-custom readback"
                );
                let echo = if matches!(command, 0x80 | 0x87 | 0x89) {
                    1
                } else {
                    0
                };
                let reply = self
                    .transport
                    .exchange(0x15, command, &record.request, echo)?;
                ensure!(
                    reply == record.response,
                    "Unrelated wheel field 15/{command:02x} changed; upload recovery refused"
                );
            }
        }
        ensure!(
            self.haptic_guard()? == backup.guard,
            "Device/state changed during upload recovery checks"
        );
        Ok(())
    }

    pub(super) fn send_original_upload(
        &mut self,
        sequence: &[Packet],
        file: &mut File,
        recovery: bool,
        journal_errors: &mut Vec<String>,
    ) -> Result<()> {
        for (index, packet) in sequence.iter().enumerate() {
            let logged = checkpoint(
                file,
                "upload_write_pending",
                json!({"recovery":recovery,"index":index}),
            );
            // The first fsynced journal already contains every original packet.
            // Later logging failures must not suppress the recovery pass.
            if recovery {
                if let Err(error) = logged {
                    journal_errors.push(format!("packet {}: {error:#}", index + 1));
                }
            } else {
                logged?;
            }
            self.transport
                .exchange(0x15, packet.command, &packet.payload, 0)
                .with_context(|| UploadStep {
                    index,
                    total: sequence.len(),
                })?;
        }
        Ok(())
    }

    pub fn replay_haptic_upload(
        &mut self,
        backup: &Backup,
        journal: &Path,
        restore_only: bool,
    ) -> Result<Value> {
        self.replay_haptic_upload_inner(backup, journal, restore_only, None)
    }

    pub fn replay_independent_haptic_upload(
        &mut self,
        checkpoint: &Value,
        journal: &Path,
        restore_only: bool,
    ) -> Result<Value> {
        let backup = super::haptic_views::independent_replay_backup(checkpoint)?;
        self.replay_haptic_upload_inner(&backup, journal, restore_only, Some(checkpoint))
    }

    fn check_upload_checkpoint(&mut self, backup: &Backup, independent: bool) -> Result<()> {
        if independent {
            self.check_independent_haptic_backup(backup)
        } else {
            self.check_haptic_backup(backup)
        }
    }

    fn replay_haptic_upload_inner(
        &mut self,
        backup: &Backup,
        journal: &Path,
        restore_only: bool,
        independent: Option<&Value>,
    ) -> Result<Value> {
        let sequence = if independent.is_some() {
            packets_with_source(backup, true)?
        } else {
            packets(backup)?
        };
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
                "Device/state changed; upload recovery refused"
            );
        }
        let backup = &normalized;
        let mut journal_errors = Vec::new();
        let mut file = if restore_only {
            let mut file = OpenOptions::new()
                .read(true)
                .append(true)
                .custom_flags(libc::O_NOFOLLOW)
                .open(journal)?;
            let meta = file.metadata()?;
            // SAFETY: geteuid has no arguments or memory preconditions.
            let uid = unsafe { libc::geteuid() };
            ensure!(
                meta.is_file()
                    && meta.len() <= 8 * 1024 * 1024
                    && meta.permissions().mode() & 0o077 == 0
                    && meta.uid() == uid,
                "Invalid private full-upload helper journal"
            );
            let mut text = String::new();
            file.read_to_string(&mut text)?;
            let first: Value =
                serde_json::from_str(text.lines().next().context("Empty full-upload journal")?)?;
            ensure!(
                first["stage"] == "haptic_upload_replay_pending"
                    && first["details"]["backup"] == json!(journal_backup)
                    && first["details"]["sequence"] == json!(sequence)
                    && first["details"]["independent_checkpoint"] == json!(independent),
                "Full-upload journal does not match original backup/sequence"
            );
            ensure!(
                !text
                    .lines()
                    .filter_map(|s| serde_json::from_str::<Value>(s).ok())
                    .any(|v| v["stage"] == "finished" && v["details"]["restored_exactly"] == true),
                "Full upload already restored; do not repeat it"
            );
            self.check_upload_recovery(backup)?;
            // The original pending header was already durable before writes.
            // A later logging failure must not suppress settings recovery.
            if let Err(error) = file.write_all(b"\n").and_then(|_| file.sync_all()) {
                journal_errors.push(format!("recovery journal separator: {error:#}"));
            }
            file
        } else {
            eprintln!("Checking full original checkpoint before any upload…");
            self.check_upload_checkpoint(backup, independent.is_some())?;
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
                json!({"backup":backup,"sequence":sequence,"independent_checkpoint":independent}),
            )?;
            self.check_upload_checkpoint(backup, independent.is_some())?;
            file
        };
        let attempted = if restore_only {
            None
        } else {
            eprintln!("Uploading original configuration and all three original tables…");
            let sent = self.send_original_upload(&sequence, &mut file, false, &mut journal_errors);
            let verified = self.check_upload_checkpoint(backup, independent.is_some());
            Some((sent, verified))
        };
        let logging_error = checkpoint(
            &mut file,
            "original_upload_restore_pending",
            json!({"restore_only":restore_only}),
        )
        .err()
        .map(|e| format!("{e:#}"));
        eprintln!("Checking unrelated state before the complete original-settings recovery pass…");
        let recovery = (|| -> Result<Value> {
            self.check_upload_recovery(backup)?;
            eprintln!(
                "Replaying the complete original upload from configuration, then verifying all captured state…"
            );
            let mut passes = Vec::new();
            for pass in 0..2 {
                let sent =
                    self.send_original_upload(&sequence, &mut file, true, &mut journal_errors);
                // Always inspect after any failure. A partial upload may have
                // changed staging without changing the saved getter state.
                let verified = self.check_upload_checkpoint(backup, independent.is_some());
                let reset_rejection = sent.as_ref().err().is_some_and(|e| {
                    e.downcast_ref::<UploadStep>()
                        .is_some_and(|s| sequence.get(s.index).is_some_and(|p| p.command == 4))
                        && e.downcast_ref::<hidraw::Rejected>()
                            .is_some_and(|r| r.class == 0x15 && r.command == 4 && r.status == 3)
                });
                let retry_boundary =
                    pass == 0 && (reset_rejection || (sent.is_ok() && verified.is_err()));
                let acknowledged = sent.is_ok();
                let matches = verified.is_ok();
                passes.push(
                    json!({"upload_acknowledged":acknowledged,"original_state_matches":matches,
                    "upload_error":sent.err().map(|e|format!("{e:#}")),
                    "verification_error":verified.err().map(|e|format!("{e:#}"))}),
                );
                if !retry_boundary {
                    return Ok(
                        json!({"upload_acknowledged":acknowledged,"original_state_matches":matches,"passes":passes}),
                    );
                }
                // A stale chunk-offset rejection resets the firmware's counters;
                // an acknowledged complete upload also reaches its reset path.
                // Recheck unrelated state, then restart at CONFIGURATION once.
                // Never retry a chunk or continue after a lost recovery ack.
                self.check_upload_recovery(backup)?;
                eprintln!("Restarting original upload once from its configuration boundary…");
            }
            unreachable!("bounded recovery returns on its second pass")
        })();
        let mut report = json!({"format":1,"kind":"haptic_upload_replay_result","restore_only":restore_only,
            "packet_count_per_upload":sequence.len(),"restored_exactly":false,"probe_passed":false,
            "journal_checkpoint_error":logging_error,"recovery_journal_errors":journal_errors});
        if independent.is_some() {
            report["kind"] = json!("haptic_independent_replay_result");
            report["active_table_verification"] = json!("selector_zero");
        }
        match recovery {
            Ok(details) => {
                report["restored_exactly"] = json!(
                    details["upload_acknowledged"] == true
                        && details["original_state_matches"] == true
                );
                report["recovery"] = details;
            }
            Err(e) => report["recovery_error"] = json!(format!("{e:#}")),
        }
        if let Some((sent, verified)) = attempted {
            report["probe_passed"] =
                json!(sent.is_ok() && verified.is_ok() && report["restored_exactly"] == true);
            report["probe_upload_error"] = json!(sent.err().map(|e| format!("{e:#}")));
            report["probe_verification_error"] = json!(verified.err().map(|e| format!("{e:#}")));
        }
        let logged = checkpoint(&mut file, "finished", report.clone());
        ensure!(
            report["restored_exactly"] == true,
            "FULL UPLOAD RESTORATION INCOMPLETE: {}",
            report.get("recovery_error").unwrap_or(&report["recovery"])
        );
        logged.context("Original full upload acknowledged and state verified, but completion journal fsync failed")?;
        Ok(report)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    type Tables = BTreeMap<(u8, u8), Vec<[u8; 8]>>;
    #[derive(Clone, Copy)]
    enum Fault {
        Lost,
        LostCorrupt,
        Reject,
        Corrupt,
        Other,
        IndependentCorrupt,
    }
    struct Device {
        config: BTreeMap<u8, Vec<u8>>,
        tables: Tables,
        staged: [Vec<[u8; 8]>; 3],
        staged_config: Vec<u8>,
        context: bool,
        complete: [bool; 3],
        table: u8,
        next: usize,
        previous: usize,
        writes: Vec<Packet>,
        fault: Option<(usize, Fault)>,
        metadata: u8,
        path: String,
        reject_tables: bool,
        alias_stored: bool,
        bad_zero: u8,
        stage_position: u8,
        stage_list: Vec<u8>,
        flash_view: Option<Tables>,
    }
    impl Device {
        fn new(counts: [usize; 3]) -> Self {
            let mut config = BTreeMap::new();
            let mut tables = BTreeMap::new();
            for slot in [1, 2] {
                let mut c = vec![0; 26];
                c[..4].copy_from_slice(&[slot, 6, 1, 1]);
                c[8..12].copy_from_slice(&12f32.to_le_bytes());
                c[16..20].copy_from_slice(&12f32.to_le_bytes());
                for (t, n) in counts.into_iter().enumerate() {
                    c[20 + t * 2..22 + t * 2].copy_from_slice(&(n as u16).to_be_bytes());
                    tables.insert(
                        (slot, t as u8 + 1),
                        (0..n)
                            .map(|i| {
                                let mut p = [0; 8];
                                p[..4].copy_from_slice(&(i as f32).to_le_bytes());
                                p[4..].copy_from_slice(
                                    &(f32::from(slot) * 0.1 + t as f32 * 0.2).to_le_bytes(),
                                );
                                p
                            })
                            .collect::<Vec<_>>(),
                    );
                }
                config.insert(slot, c);
            }
            Self {
                staged: std::array::from_fn(|i| tables[&(1, i as u8 + 1)].clone()),
                staged_config: config[&1].clone(),
                config,
                tables,
                context: false,
                complete: [false; 3],
                table: 0,
                next: 0,
                previous: 0,
                writes: vec![],
                fault: None,
                metadata: 0xa5,
                path: "mock".into(),
                reject_tables: false,
                alias_stored: false,
                bad_zero: 0,
                stage_position: 5,
                stage_list: vec![0x81, 0x82, 0x83, 0x84, 0x85],
                flash_view: None,
            }
        }
        fn reject(&mut self) -> Result<Vec<u8>> {
            self.context = false;
            Err(hidraw::Rejected {
                class: 0x15,
                command: 4,
                status: 3,
            }
            .into())
        }
    }
    impl Transport for Device {
        fn identity(&self) -> Identity {
            Identity {
                path: self.path.clone(),
                product: 0xa7,
                serial: String::new(),
            }
        }
        fn exchange(&mut self, class: u8, command: u8, p: &[u8], _: usize) -> Result<Vec<u8>> {
            if class == 0x15 && command < 0x80 {
                assert!(matches!(command, 3 | 4 | 7), "No other setters permitted");
                self.writes.push(Packet {
                    command,
                    payload: p.to_vec(),
                });
                let fault = if self.fault.is_some_and(|(at, _)| at == self.writes.len()) {
                    self.fault.take().map(|(_, f)| f)
                } else {
                    None
                };
                if matches!(fault, Some(Fault::Reject)) {
                    self.context = false;
                    return Err(hidraw::Rejected {
                        class,
                        command,
                        status: 3,
                    }
                    .into());
                }
                if command == 4 && self.reject_tables {
                    return self.reject();
                }
                if command == 7 {
                    assert_eq!(p.len(), 13);
                    self.stage_position = p[1];
                    self.stage_list = p[3..3 + usize::from(p[2])].to_vec();
                    if matches!(fault, Some(Fault::Lost)) {
                        bail!("Lost stage acknowledgement");
                    }
                    return Ok(vec![]);
                }
                assert_eq!(&p[..2], &[1, 6]);
                if command == 3 {
                    assert_eq!(p.len(), 26);
                    self.staged_config = p.to_vec();
                    self.context = true;
                    self.complete = [false; 3];
                    // Firmware configuration resets context, not chunk counters.
                } else {
                    let t = usize::from(p[2] - 1);
                    assert!(t < 3);
                    let start = usize::from(u16::from_be_bytes([p[3], p[4]]));
                    let count = usize::from(u16::from_be_bytes([p[5], p[6]]));
                    assert!((1..=8).contains(&count));
                    assert_eq!(p.len(), 10 + 8 * count);
                    assert_eq!(&p[p.len() - 3..], &[0, 0, 0]);
                    let total = usize::from(u16::from_be_bytes([
                        self.staged_config[20 + t * 2],
                        self.staged_config[21 + t * 2],
                    ]));
                    assert!(start + count <= total);
                    if !self.context || (t > 0 && !self.complete[t - 1]) {
                        return self.reject();
                    }
                    if self.table != p[2] {
                        self.table = p[2];
                        self.previous = 0;
                    }
                    if start != self.next {
                        if start != self.previous {
                            self.next = 0;
                            self.previous = 0;
                            return self.reject();
                        } // Firmware recognizes the previous offset as duplicate.
                    } else {
                        if t == 0 && start == 0 {
                            for values in &mut self.staged {
                                values.fill([0; 8]);
                            }
                        }
                        for i in 0..count {
                            self.staged[t][start + i].copy_from_slice(&p[7 + i * 8..15 + i * 8]);
                        }
                        self.previous = start;
                        self.next = if start + count == total {
                            0
                        } else {
                            start + count
                        };
                    }
                    if start + count == total {
                        self.complete[t] = true;
                        if t == 2 {
                            for i in 0..3 {
                                self.tables.insert((1, i as u8 + 1), self.staged[i].clone());
                            }
                            self.config.insert(1, self.staged_config.clone());
                        }
                    }
                    if matches!(fault, Some(Fault::Corrupt | Fault::LostCorrupt)) {
                        self.staged[t][start][..4].copy_from_slice(&f32::NAN.to_le_bytes());
                    }
                }
                if matches!(fault, Some(Fault::Other)) {
                    self.metadata ^= 1;
                }
                if matches!(fault, Some(Fault::IndependentCorrupt)) {
                    self.tables.get_mut(&(1, 3)).unwrap()[0][4..]
                        .copy_from_slice(&0.75f32.to_le_bytes());
                }
                if matches!(fault, Some(Fault::Lost | Fault::LostCorrupt)) {
                    bail!("Accepted; acknowledgement lost");
                }
                return Ok(vec![]);
            }
            Ok(match (class, command) {
                (0, 0x82) => {
                    let mut r = vec![0; 22];
                    r[..4].copy_from_slice(b"TEST");
                    r
                }
                (0, 0x84) => vec![0, 0],
                (5, 0x81) => vec![5, 1, 2],
                (5, 0x84) => vec![1, 0, 0, 0, 0, 0],
                (0, 0xb9) => vec![3],
                (2, 0x8c) => {
                    let mut r = p.to_vec();
                    r[3..].fill(0);
                    r[3..6].copy_from_slice(&[1, 1, if p[1] <= 3 { p[1] } else { 4 }]);
                    r
                }
                (0x15, 0x80) => vec![p[0], if p[0] == 1 { self.stage_position } else { 5 }],
                (0x15, 0x87) => {
                    let list = if p[0] == 1 {
                        self.stage_list.clone()
                    } else {
                        vec![0x81, 0x82, 0x83, 0x84, 0x85]
                    };
                    let mut r = vec![
                        p[0],
                        if p[0] == 1 { self.stage_position } else { 5 },
                        list.len() as u8,
                    ];
                    r.extend(list);
                    r.resize(13, 0);
                    r
                }
                (0x15, 0x88) => vec![0],
                (0x15, 0x85) => vec![0, 80, 0, 80, 0, 80],
                (0x15, 0x83) => {
                    if p[0] == 0 && self.bad_zero == 3 {
                        bail!("Selector zero rejected");
                    }
                    let mut r = self.config[&p[0].max(1)].clone();
                    r[0] = p[0];
                    if p[0] == 0 && self.bad_zero == 1 {
                        r[8] ^= 1;
                    }
                    r
                }
                (0x15, 0x84) => {
                    let start = usize::from(u16::from_be_bytes([p[3], p[4]]));
                    let count = usize::from(u16::from_be_bytes([p[5], p[6]]));
                    let mut r = p.to_vec();
                    let source = if p[0] != 0 && self.alias_stored {
                        1
                    } else {
                        p[2]
                    };
                    for i in 0..count {
                        let tables = if p[0] == 0 {
                            self.flash_view.as_ref().unwrap_or(&self.tables)
                        } else {
                            &self.tables
                        };
                        r[7 + i * 8..15 + i * 8]
                            .copy_from_slice(&tables[&(p[0].max(1), source)][start + i]);
                    }
                    if p[0] == 0 && self.bad_zero == 2 {
                        r[7] ^= 1;
                    }
                    r
                }
                (0x15, 0x89) => {
                    let mut r = vec![p[0], 40];
                    r.resize(66, self.metadata);
                    r
                }
                _ => bail!("Unexpected command {class:02x}/{command:02x}"),
            })
        }
    }
    struct Temp(std::path::PathBuf);
    impl Temp {
        fn new() -> Self {
            static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let p = std::env::temp_dir().join(format!(
                "nagalibre-upload-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
            ));
            std::fs::create_dir(&p).unwrap();
            Self(p)
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    fn setup(counts: [usize; 3]) -> (Mouse<Device>, Backup, Temp) {
        let mut m = Mouse {
            transport: Device::new(counts),
        };
        let before = m.inspect_haptic(None).unwrap();
        let prepared = m
            .prepare_haptic(
                &before,
                super::super::haptic_transaction::Edit {
                    active_position: 5,
                    stages: before.state.stages.clone(),
                },
            )
            .unwrap();
        (m, prepared.backup, Temp::new())
    }
    #[test]
    fn independent_checkpoint_preserves_separate_tables_and_rejects_legacy_deserialization() {
        let mut m = Mouse {
            transport: Device::new([43, 43, 5]),
        };
        m.transport.alias_stored = true;
        // Observed slot-2 control: stored velocity is a CW prefix while selector
        // zero has an independent velocity response beginning at -720 degrees/s.
        let velocity = m.transport.tables.get_mut(&(1, 3)).unwrap();
        velocity[0][..4].copy_from_slice(&(-720f32).to_le_bytes());
        velocity[0][4..].copy_from_slice(&1.5067f32.to_le_bytes());
        let checkpoint = m.inspect_haptic_independent_checkpoint().unwrap();
        assert_eq!(checkpoint["kind"], "haptic_independent_checkpoint");
        assert_eq!(
            checkpoint["table_views"]["stored_matches_live"],
            json!([true, false, false])
        );
        assert_eq!(
            checkpoint["table_views"]["live"]["tables"],
            json!([
                m.transport.tables[&(1, 1)],
                m.transport.tables[&(1, 2)],
                m.transport.tables[&(1, 3)]
            ])
        );
        assert!(serde_json::from_value::<Backup>(checkpoint).is_err());
        assert!(m.transport.writes.is_empty());
    }
    #[test]
    fn independent_checkpoint_preserves_actual_overlap_without_inventing_velocity() {
        let mut m = Mouse {
            transport: Device::new([45, 45, 3]),
        };
        let prefix = m.transport.tables[&(1, 1)][..3].to_vec();
        m.transport.tables.insert((1, 3), prefix.clone());
        m.transport.alias_stored = true;
        let checkpoint = m.inspect_haptic_independent_checkpoint().unwrap();
        assert_eq!(
            checkpoint["table_views"]["live"]["tables"][2],
            json!(prefix)
        );
        assert_eq!(checkpoint["table_views"]["live_prefix_overlap"], true);
        assert!(m.transport.writes.is_empty());
    }
    #[test]
    fn independent_checkpoint_stops_on_wrong_configuration_cw_or_rejected_selector() {
        for bad_zero in 1..=3 {
            let mut m = Mouse {
                transport: Device::new([43, 43, 5]),
            };
            m.transport.alias_stored = true;
            m.transport.bad_zero = bad_zero;
            assert!(
                m.inspect_haptic_independent_checkpoint().is_err(),
                "case {bad_zero}"
            );
            assert!(m.transport.writes.is_empty());
        }
    }
    #[test]
    fn captured_counts_generate_config_then_all_original_chunks_and_preserve_velocity() {
        let (mut m, b, t) = setup([45, 45, 3]);
        let seq = packets(&b).unwrap();
        assert_eq!(seq.len(), 14);
        assert_eq!(seq[0].command, 3);
        assert_eq!(seq[0].payload, b.slots[0].configuration);
        assert_eq!(&seq[6].payload[..7], &[1, 6, 1, 0, 40, 0, 5]);
        assert_eq!(&seq[12].payload[..7], &[1, 6, 2, 0, 40, 0, 5]);
        assert_eq!(&seq[13].payload[..7], &[1, 6, 3, 0, 0, 0, 3]);
        let r = m
            .replay_haptic_upload(&b, &t.0.join("journal"), false)
            .unwrap();
        assert_eq!(r["probe_passed"], true);
        assert_eq!(m.transport.writes.len(), 28);
        m.check_haptic_backup(&b).unwrap();
    }
    #[test]
    fn custom_velocity_trial_preserves_cw_ccw_and_restores_current_tables_and_stage() {
        let mut m = Mouse {
            transport: Device::new([45, 45, 3]),
        };
        m.transport.alias_stored = true;
        let before = m.transport.tables.clone();
        let captured = m.inspect_haptic_independent_checkpoint().unwrap();
        let t = Temp::new();
        let journal = t.0.join("journal");
        let result = m
            .trial_haptic_unit_velocity(&captured, &journal, false)
            .unwrap();
        assert_eq!(result["applied"], true);
        assert_eq!(m.transport.stage_position, 6);
        assert_eq!(m.transport.tables[&(1, 1)], before[&(1, 1)]);
        assert_eq!(m.transport.tables[&(1, 2)], before[&(1, 2)]);
        for (point, x) in m.transport.tables[&(1, 3)].iter().zip([-720f32, 0., 720.]) {
            assert_eq!(&point[..4], &x.to_le_bytes());
            assert_eq!(&point[4..], &1f32.to_le_bytes());
        }
        m.transport.path = "reconnected".into();
        let result = m
            .trial_haptic_unit_velocity(&captured, &journal, true)
            .unwrap();
        assert_eq!(result["restored_exactly"], true);
        assert_eq!(m.transport.tables, before);
        assert_eq!(m.transport.stage_position, 5);
        assert_eq!(m.transport.stage_list, vec![0x81, 0x82, 0x83, 0x84, 0x85]);
        let writes = m.transport.writes.len();
        assert!(
            m.trial_haptic_unit_velocity(&captured, &journal, true)
                .is_err()
        );
        assert_eq!(m.transport.writes.len(), writes);
    }
    #[test]
    fn custom_velocity_trial_lost_ack_at_each_apply_packet_and_selection_recovers() {
        for at in 1..=15 {
            let mut m = Mouse {
                transport: Device::new([45, 45, 3]),
            };
            m.transport.alias_stored = true;
            let before = m.transport.tables.clone();
            let captured = m.inspect_haptic_independent_checkpoint().unwrap();
            let t = Temp::new();
            m.transport.fault = Some((at, Fault::Lost));
            let result = m
                .trial_haptic_unit_velocity(&captured, &t.0.join("journal"), false)
                .unwrap();
            assert_eq!(result["applied"], false, "packet {at}");
            assert_eq!(result["restored_exactly"], true);
            assert_eq!(m.transport.tables, before);
            assert_eq!(m.transport.stage_position, 5);
        }
    }
    #[test]
    fn custom_trial_recovery_does_not_parse_partial_tables_or_overwrite_unrelated_changes() {
        let mut m = Mouse {
            transport: Device::new([45, 45, 3]),
        };
        m.transport.alias_stored = true;
        let captured = m.inspect_haptic_independent_checkpoint().unwrap();
        let before = m.transport.tables.clone();
        let t = Temp::new();
        let journal = t.0.join("journal");
        m.trial_haptic_unit_velocity(&captured, &journal, false)
            .unwrap();
        m.transport.tables.get_mut(&(1, 1)).unwrap()[0][..4]
            .copy_from_slice(&f32::NAN.to_le_bytes());
        let result = m
            .trial_haptic_unit_velocity(&captured, &journal, true)
            .unwrap();
        assert_eq!(result["restored_exactly"], true);
        assert_eq!(m.transport.tables, before);
        let next = t.0.join("next");
        m.trial_haptic_unit_velocity(&captured, &next, false)
            .unwrap();
        m.transport.metadata ^= 1;
        let writes = m.transport.writes.len();
        assert!(
            m.trial_haptic_unit_velocity(&captured, &next, true)
                .is_err()
        );
        assert_eq!(m.transport.writes.len(), writes);
    }
    #[test]
    fn custom_trial_stage_restore_lost_ack_is_checked_and_curve_ack_failure_can_resume() {
        for packet in [16, 17] {
            let mut m = Mouse {
                transport: Device::new([45, 45, 3]),
            };
            m.transport.alias_stored = true;
            let original = m.transport.tables.clone();
            let captured = m.inspect_haptic_independent_checkpoint().unwrap();
            let t = Temp::new();
            let path = t.0.join("journal");
            m.trial_haptic_unit_velocity(&captured, &path, false)
                .unwrap();
            m.transport.fault = Some((packet, Fault::Lost));
            if packet == 16 {
                let result = m
                    .trial_haptic_unit_velocity(&captured, &path, true)
                    .unwrap();
                assert_eq!(result["restored_exactly"], true);
                assert_eq!(
                    result["stage_restore_ack_errors"].as_array().unwrap().len(),
                    1
                );
            } else {
                assert!(
                    m.trial_haptic_unit_velocity(&captured, &path, true)
                        .is_err()
                );
                let result = m
                    .trial_haptic_unit_velocity(&captured, &path, true)
                    .unwrap();
                assert_eq!(result["restored_exactly"], true);
            }
            assert_eq!(m.transport.tables, original);
            assert_eq!(m.transport.stage_position, 5);
        }
    }
    #[test]
    fn custom_trial_records_exact_mismatch_before_recovery_and_returns_it_unprivileged() {
        let mut m = Mouse {
            transport: Device::new([45, 45, 3]),
        };
        m.transport.alias_stored = true;
        let before = m.transport.tables.clone();
        let captured = m.inspect_haptic_independent_checkpoint().unwrap();
        let t = Temp::new();
        let journal = t.0.join("journal");
        m.transport.fault = Some((14, Fault::IndependentCorrupt));
        let result = m
            .trial_haptic_unit_velocity(&captured, &journal, false)
            .unwrap();
        assert_eq!(result["applied"], false);
        assert_eq!(result["restored_exactly"], true);
        assert!(
            result["apply_error"]
                .as_str()
                .unwrap()
                .contains("before Custom selection")
        );
        let diff = &result["state_mismatch"];
        assert_eq!(diff["slot"], 1);
        assert!(
            diff["fields"]
                .as_array()
                .unwrap()
                .contains(&json!("tables[2]"))
        );
        assert_ne!(diff["expected"]["tables"][2], diff["observed"]["tables"][2]);
        assert!(diff["observed"].get("device").is_none());
        let lines: Vec<Value> = std::fs::read_to_string(journal)
            .unwrap()
            .lines()
            .filter(|s| !s.trim().is_empty())
            .map(|s| serde_json::from_str(s).unwrap())
            .collect();
        let at = lines
            .iter()
            .position(|r| r["stage"] == "trial_state_mismatch")
            .unwrap();
        let recovery = lines
            .iter()
            .position(|r| r["stage"] == "original_upload_restore_pending")
            .unwrap();
        assert!(at < recovery);
        assert_eq!(&lines[at]["details"], diff);
        assert_eq!(m.transport.tables, before);
        assert_eq!(m.transport.stage_position, 5);
    }
    #[test]
    fn captured_unchanged_flash_velocity_after_acknowledged_upload_stops_before_custom() {
        let mut m = Mouse {
            transport: Device::new([45, 45, 3]),
        };
        m.transport.alias_stored = true;
        let prefix = m.transport.tables[&(1, 1)][..3].to_vec();
        m.transport.tables.insert((1, 3), prefix.clone());
        let original = m.transport.tables.clone();
        m.transport.flash_view = Some(original.clone());
        let captured = m.inspect_haptic_independent_checkpoint().unwrap();
        let t = Temp::new();
        let result = m
            .trial_haptic_unit_velocity(&captured, &t.0.join("journal"), false)
            .unwrap();
        assert_eq!(result["applied"], false);
        assert_eq!(result["restored_exactly"], true);
        assert_eq!(
            result["state_mismatch"]["observed"]["tables"][2],
            json!(prefix)
        );
        assert_ne!(
            result["state_mismatch"]["expected"]["tables"][2],
            json!(prefix)
        );
        assert!(m.transport.writes.iter().all(|p| p.command != 7));
        assert_eq!(m.transport.tables, original);
        assert_eq!(m.transport.flash_view, Some(original));
    }
    #[test]
    fn independent_replay_recovers_corruption_invisible_to_stored_getters() {
        let mut m = Mouse {
            transport: Device::new([43, 43, 5]),
        };
        m.transport.alias_stored = true;
        let captured = m.inspect_haptic_independent_checkpoint().unwrap();
        let original = m.transport.tables.clone();
        let baseline: Backup = serde_json::from_value(captured["baseline"].clone()).unwrap();
        m.transport.tables.get_mut(&(1, 3)).unwrap()[0][4..]
            .copy_from_slice(&0.75f32.to_le_bytes());
        // The old getter check passes despite changed actual velocity.
        m.check_haptic_backup(&baseline).unwrap();
        let t = Temp::new();
        assert!(
            m.replay_independent_haptic_upload(&captured, &t.0.join("stale"), false)
                .is_err()
        );
        assert!(m.transport.writes.is_empty());
        assert!(!t.0.join("stale").exists());
        m.transport.tables = original.clone();
        m.transport.fault = Some((14, Fault::IndependentCorrupt));
        let r = m
            .replay_independent_haptic_upload(&captured, &t.0.join("journal"), false)
            .unwrap();
        assert_eq!(r["probe_passed"], false);
        assert_eq!(r["restored_exactly"], true);
        assert_eq!(r["active_table_verification"], "selector_zero");
        assert_eq!(m.transport.tables, original);
    }
    #[test]
    fn independent_replay_preserves_real_prefix_overlap_and_rejects_completed_repeat() {
        let mut m = Mouse {
            transport: Device::new([45, 45, 3]),
        };
        let prefix = m.transport.tables[&(1, 1)][..3].to_vec();
        m.transport.tables.insert((1, 3), prefix.clone());
        m.transport.alias_stored = true;
        let captured = m.inspect_haptic_independent_checkpoint().unwrap();
        let t = Temp::new();
        let path = t.0.join("journal");
        let r = m
            .replay_independent_haptic_upload(&captured, &path, false)
            .unwrap();
        assert_eq!(r["probe_passed"], true);
        assert_eq!(m.transport.tables[&(1, 3)], prefix);
        assert_eq!(m.transport.writes.len(), 28);
        assert!(
            m.replay_independent_haptic_upload(&captured, &path, true)
                .is_err()
        );
        assert_eq!(m.transport.writes.len(), 28);
    }
    #[test]
    fn independent_lost_initial_ack_at_every_packet_restores_from_configuration() {
        for at in 1..=14 {
            let mut m = Mouse {
                transport: Device::new([43, 43, 5]),
            };
            m.transport.alias_stored = true;
            let captured = m.inspect_haptic_independent_checkpoint().unwrap();
            let original = m.transport.tables.clone();
            let t = Temp::new();
            m.transport.fault = Some((at, Fault::Lost));
            let r = m
                .replay_independent_haptic_upload(&captured, &t.0.join("journal"), false)
                .unwrap();
            assert_eq!(r["restored_exactly"], true, "packet {at}");
            assert_eq!(r["probe_passed"], false);
            assert_eq!(m.transport.writes[at].command, 3);
            assert_eq!(m.transport.tables, original);
        }
    }
    #[test]
    fn independent_recovery_rejects_legacy_policy_and_resumes_after_lost_recovery_ack() {
        let mut m = Mouse {
            transport: Device::new([43, 43, 5]),
        };
        m.transport.alias_stored = true;
        let captured = m.inspect_haptic_independent_checkpoint().unwrap();
        let backup = super::super::haptic_views::independent_replay_backup(&captured).unwrap();
        let t = Temp::new();
        let path = t.0.join("journal");
        m.transport.fault = Some((15, Fault::Lost));
        assert!(
            m.replay_independent_haptic_upload(&captured, &path, false)
                .is_err()
        );
        let writes = m.transport.writes.len();
        assert!(m.replay_haptic_upload(&backup, &path, true).is_err());
        assert_eq!(m.transport.writes.len(), writes);
        let r = m
            .replay_independent_haptic_upload(&captured, &path, true)
            .unwrap();
        assert_eq!(r["restored_exactly"], true);
        assert_eq!(r["probe_passed"], false);
    }
    #[test]
    fn lost_initial_ack_at_every_packet_restarts_full_original_sequence() {
        for at in 1..=14 {
            let (mut m, b, t) = setup([45, 45, 3]);
            m.transport.fault = Some((at, Fault::Lost));
            let r = m
                .replay_haptic_upload(&b, &t.0.join("journal"), false)
                .unwrap();
            assert_eq!(r["probe_passed"], false, "packet {at}");
            assert_eq!(r["restored_exactly"], true);
            assert_eq!(m.transport.writes[at].command, 3);
            m.check_haptic_backup(&b).unwrap();
        }
    }
    #[test]
    fn corrupted_partial_data_gets_complete_recovery_and_exact_unmasked_verification() {
        let (mut m, b, t) = setup([9, 9, 3]);
        m.transport.fault = Some((2, Fault::Corrupt));
        let r = m
            .replay_haptic_upload(&b, &t.0.join("journal"), false)
            .unwrap();
        assert_eq!(r["probe_passed"], false);
        assert_eq!(r["restored_exactly"], true);
        m.check_haptic_backup(&b).unwrap();
    }
    #[test]
    fn duplicate_first_chunk_with_damaged_staging_requires_second_complete_recovery_pass() {
        let (mut m, b, t) = setup([9, 9, 3]);
        m.transport.fault = Some((2, Fault::LostCorrupt));
        let r = m
            .replay_haptic_upload(&b, &t.0.join("journal"), false)
            .unwrap();
        assert_eq!(r["restored_exactly"], true);
        assert_eq!(r["probe_passed"], false);
        assert_eq!(r["recovery"]["passes"].as_array().unwrap().len(), 2);
        m.check_haptic_backup(&b).unwrap();
    }
    #[test]
    fn lost_recovery_ack_is_incomplete_even_when_saved_readbacks_match() {
        for at in 7..=12 {
            let (mut m, b, t) = setup([9, 9, 3]);
            m.transport.fault = Some((at, Fault::Lost));
            let path = t.0.join("journal");
            let error = m.replay_haptic_upload(&b, &path, false).unwrap_err();
            assert!(error.to_string().contains("RESTORATION INCOMPLETE"));
            let r = m.replay_haptic_upload(&b, &path, true).unwrap();
            assert_eq!(r["restored_exactly"], true);
            assert_eq!(r["probe_passed"], false);
        }
    }
    #[test]
    fn counter_rejection_on_first_cw_restarts_at_configuration_once() {
        let (mut m, b, t) = setup([45, 45, 3]);
        let seq = packets(&b).unwrap();
        let path = t.0.join("journal");
        let mut f = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .unwrap();
        checkpoint(
            &mut f,
            "haptic_upload_replay_pending",
            json!({"backup":b,"sequence":seq}),
        )
        .unwrap();
        for packet in seq.iter().take(4) {
            m.transport
                .exchange(0x15, packet.command, &packet.payload, 0)
                .unwrap();
        }
        m.transport.path = "new-hidraw".into();
        let r = m.replay_haptic_upload(&b, &path, true).unwrap();
        assert_eq!(r["recovery"]["passes"].as_array().unwrap().len(), 2);
        assert_eq!(r["restored_exactly"], true);
        let n = m.transport.writes.len();
        assert!(m.replay_haptic_upload(&b, &path, true).is_err());
        assert_eq!(m.transport.writes.len(), n);
    }
    #[test]
    fn unrelated_changes_and_rejected_recovery_configuration_never_report_success() {
        for fault in [Fault::Other, Fault::Reject] {
            let (mut m, b, t) = setup([9, 9, 3]);
            m.transport.fault = Some((if matches!(fault, Fault::Other) { 1 } else { 7 }, fault));
            let error = m
                .replay_haptic_upload(&b, &t.0.join("journal"), false)
                .unwrap_err();
            assert!(error.to_string().contains("RESTORATION INCOMPLETE"));
        }
    }
    #[test]
    fn persistent_chunk_rejection_stops_after_bounded_whole_sequence_recovery() {
        let (mut m, b, t) = setup([9, 9, 3]);
        m.transport.reject_tables = true;
        let error = m
            .replay_haptic_upload(&b, &t.0.join("journal"), false)
            .unwrap_err();
        assert!(error.to_string().contains("RESTORATION INCOMPLETE"));
        assert_eq!(m.transport.writes.len(), 6);
        assert_eq!(
            m.transport
                .writes
                .iter()
                .map(|p| p.command)
                .collect::<Vec<_>>(),
            vec![3, 4, 3, 4, 3, 4]
        );
        m.check_haptic_backup(&b).unwrap(); // Matching saved state is insufficient.
    }
    #[test]
    fn recovery_continues_on_journal_write_failure_but_initial_upload_never_starts() {
        for recovery in [false, true] {
            let (mut m, b, t) = setup([9, 9, 3]);
            let path = t.0.join("journal");
            std::fs::write(&path, b"durable original checkpoint\n").unwrap();
            let mut file = File::open(&path).unwrap(); // Read-only descriptor fails writes.
            let mut errors = Vec::new();
            let result =
                m.send_original_upload(&packets(&b).unwrap(), &mut file, recovery, &mut errors);
            assert_eq!(result.is_ok(), recovery);
            assert_eq!(m.transport.writes.len(), if recovery { 6 } else { 0 });
            assert_eq!(errors.len(), if recovery { 6 } else { 0 });
            m.check_haptic_backup(&b).unwrap();
        }
    }
    #[test]
    fn overlapping_stored_velocity_view_blocks_upload_before_any_write() {
        let (mut m, mut b, t) = setup([45, 45, 3]);
        b.slots[0].tables[2] = b.slots[0].tables[0][..3].to_vec();
        let error = m
            .replay_haptic_upload(&b, &t.0.join("journal"), false)
            .unwrap_err();
        assert!(
            error
                .to_string()
                .contains("independent table backup/recovery is unverified")
        );
        assert!(m.transport.writes.is_empty());
        assert!(!t.0.join("journal").exists());
    }
    #[test]
    fn stale_state_existing_journal_and_invalid_original_counts_prevent_writes() {
        for mode in 0..3 {
            let (mut m, mut b, t) = setup([9, 9, 3]);
            let path = t.0.join("journal");
            match mode {
                0 => m.transport.metadata ^= 1,
                1 => std::fs::write(&path, b"existing").unwrap(),
                _ => b.slots[0].configuration[21] = 80,
            }
            assert!(m.replay_haptic_upload(&b, &path, false).is_err());
            assert!(m.transport.writes.is_empty());
        }
    }
}
