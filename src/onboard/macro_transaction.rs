//! Fresh-only macro uploads with durable intent, exact readback and owned cleanup.
//! Existing macro entries are never overwritten, removed, compacted or formatted.
use super::*;
use std::{
    fs::{File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    os::{
        fd::AsRawFd,
        unix::fs::{MetadataExt, OpenOptionsExt},
    },
    path::Path,
};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Backup {
    pub format: u8,
    pub kind: String,
    pub complete_profile: bool,
    pub contents: macros::Checkpoint,
    pub mappings: layer_transaction::LayerBackup,
    pub config: String,
    pub request: macro_plan::Request,
}

pub struct Prepared {
    backup: Backup,
    plan: macro_plan::Plan,
}

impl Prepared {
    pub fn backup(&self) -> &Backup {
        &self.backup
    }
}

#[derive(Default, Clone, Copy)]
struct Progress {
    attempted: bool,
    identified: bool,
    complete: bool,
}

impl Backup {
    fn plan(&self) -> Result<macro_plan::Plan> {
        ensure!(
            self.format == 1
                && self.kind == "onboard_macro_transaction_backup"
                && !self.complete_profile
                && self.config.len() <= 262_144,
            "Invalid macro transaction backup"
        );
        self.contents.validate()?;
        let before = &self.contents.inspection;
        ensure!(
            self.mappings.format == 1
                && self.mappings.kind == "paired_mapping_backup"
                && self.mappings.slots.len() == before.mappings.len(),
            "Incomplete macro mapping backup"
        );
        for (slot, mapping) in self.mappings.slots.iter().zip(&before.mappings) {
            ensure!(
                &slot.state == mapping
                    && slot.middle.button == 3
                    && slot.middle.category == 1
                    && slot.middle.data == [3],
                "Macro mapping backup differs from contents checkpoint"
            );
            slot.middle.record()?;
        }
        let bindings = crate::config::parse(&self.config)?;
        let sequence = bindings
            .iter()
            .find(|(k, _)| format!("{k:?}") == self.request.trigger)
            .map(|(_, v)| v)
            .context("Macro trigger is absent from configuration")?;
        let plan = macro_plan::build(self.contents.clone(), sequence, self.request.clone())?;
        let active = before
            .mappings
            .iter()
            .find(|m| m.normal.slot == before.guard.active)
            .context("Active mappings missing")?;
        ensure!(
            active
                .normal_echoes
                .iter()
                .find(|e| e.button == self.request.button)
                == active
                    .hypershift
                    .echoes
                    .iter()
                    .find(|e| e.button == self.request.button),
            "Target banks have inconsistent selector echoes; exact restoration is unavailable"
        );
        Ok(plan)
    }

    fn at_path(&self, path: &str) -> Self {
        let mut b = self.clone();
        b.contents.inspection.guard.device.path = path.into();
        for m in &mut b.contents.inspection.mappings {
            m.normal.device.path = path.into();
        }
        for m in &mut b.mappings.slots {
            m.state.normal.device.path = path.into();
        }
        b
    }
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case", deny_unknown_fields)]
enum Event {
    Prepared { backup: Box<Backup> },
    PacketPending { index: usize },
    PacketAcknowledged { index: usize },
    BindingPending,
    Saved,
    Recovering,
    RemovalPending,
    Recovered,
}

struct Journal {
    file: File,
    poisoned: bool,
}

fn lock(file: &File) -> Result<()> {
    // Advisory lock serializes NagaLibre recovery clients, without claiming a
    // lock against vendor applications or other HID users.
    ensure!(
        unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0,
        "Macro journal is already in use"
    );
    Ok(())
}

impl Journal {
    fn create(path: &Path, backup: &Backup) -> Result<Self> {
        let parent = path
            .parent()
            .context("Macro journal needs a parent directory")?;
        let metadata = std::fs::symlink_metadata(parent)?;
        let uid = std::env::var("PKEXEC_UID")
            .or_else(|_| std::env::var("SUDO_UID"))
            .ok()
            .and_then(|s| s.parse::<u32>().ok())
            .unwrap_or_else(|| unsafe { libc::geteuid() });
        ensure!(
            metadata.is_dir() && metadata.uid() == uid && metadata.mode() & 0o077 == 0,
            "Macro journal parent must be a private directory owned by the invoking user"
        );
        let file = OpenOptions::new()
            .read(true)
            .append(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)
            .context("Creating exclusive macro transaction journal")?;
        lock(&file)?;
        let mut result = Self {
            file,
            poisoned: false,
        };
        result.record(&Event::Prepared {
            backup: Box::new(backup.clone()),
        })?;
        File::open(parent)?.sync_all()?;
        Ok(result)
    }

    fn record(&mut self, event: &Event) -> Result<()> {
        ensure!(
            !self.poisoned,
            "Macro journal needs reopening after an I/O failure"
        );
        let mut bytes = serde_json::to_vec(event)?;
        bytes.push(b'\n');
        let start = self.file.metadata()?.len();
        let result = self
            .file
            .write_all(&bytes)
            .and_then(|_| self.file.sync_all());
        if let Err(error) = result {
            // Never append another event behind a torn JSON line. Keep the last
            // durable intent (including a pending request whose ACK was lost).
            self.poisoned = true;
            if self.file.set_len(start).is_ok() {
                let _ = self.file.sync_all();
            }
            return Err(error).context("Saving macro journal; original durable intent retained");
        }
        Ok(())
    }

    fn open(path: &Path) -> Result<(Self, Backup, Progress)> {
        let mut file = OpenOptions::new()
            .read(true)
            .append(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)?;
        lock(&file)?;
        let stat = file.metadata()?;
        ensure!(
            stat.is_file()
                && stat.nlink() == 1
                && stat.uid() == unsafe { libc::geteuid() }
                && stat.mode() & 0o077 == 0
                && stat.len() <= 64 * 1024 * 1024,
            "Recovery requires a private journal owned by the helper, not a user-supplied upload plan"
        );
        let mut bytes = Vec::new();
        Read::by_ref(&mut file)
            .take(64 * 1024 * 1024 + 1)
            .read_to_end(&mut bytes)?;
        ensure!(
            bytes.len() <= 64 * 1024 * 1024,
            "Macro journal exceeds resource bound"
        );
        let end = bytes
            .iter()
            .rposition(|b| *b == b'\n')
            .context("Incomplete macro journal header")?
            + 1;
        let mut events = bytes[..end]
            .split(|b| *b == b'\n')
            .filter(|s| !s.is_empty());
        let Event::Prepared { backup } =
            serde_json::from_slice(events.next().context("Missing macro journal header")?)?
        else {
            bail!("Invalid macro journal header")
        };
        let plan = backup.plan()?;
        let mut next = 0;
        let mut pending = false;
        let mut attempted = false;
        let mut identified = false;
        let mut bound = false;
        let mut recovering = false;
        let mut recovered = false;
        for line in events {
            match serde_json::from_slice::<Event>(line)? {
                Event::PacketPending { index }
                    if !recovering
                        && !bound
                        && !recovered
                        && !pending
                        && index == next
                        && index < plan.upload.len() =>
                {
                    pending = true;
                    attempted = true;
                }
                Event::PacketAcknowledged { index } if !recovering && pending && index == next => {
                    pending = false;
                    next += 1;
                    identified |= index >= 1;
                }
                Event::BindingPending
                    if !recovering && !pending && next == plan.upload.len() && !bound =>
                {
                    bound = true
                }
                Event::Saved if bound && !recovering => {}
                Event::Recovering if !recovered => recovering = true,
                Event::RemovalPending if recovering && attempted && !recovered => {}
                Event::Recovered if recovering => recovered = true,
                _ => bail!("Invalid macro journal event order"),
            }
        }
        // An interrupted final append never authorizes a new mutation. Keep
        // complete durable intent and discard only the unterminated tail.
        if end < bytes.len() {
            file.set_len(end as u64)?;
            file.sync_all()?;
        }
        file.seek(SeekFrom::End(0))?;
        Ok((
            Self {
                file,
                poisoned: false,
            },
            *backup,
            Progress {
                attempted,
                identified,
                complete: recovered,
            },
        ))
    }
}

fn entries(storage: &macros::Storage) -> Vec<&macros::Entry> {
    let mut result: Vec<_> = storage.entries.iter().collect();
    result.sort_by_key(|e| e.id);
    result
}

fn unchanged_storage(
    before: &macros::Storage,
    after: &macros::Storage,
    new: &macros::Entry,
    require_uploaded: bool,
) -> Result<bool> {
    ensure!(
        before.max_macros == after.max_macros && before.storage_bytes == after.storage_bytes,
        "Macro storage capacity changed"
    );
    let own = after.entries.iter().find(|e| e.id == new.id);
    let mut untouched = after.clone();
    untouched.entries.retain(|e| e.id != new.id);
    ensure!(
        entries(before) == entries(&untouched),
        "An existing or unrelated macro changed; recovery stopped"
    );
    if require_uploaded {
        ensure!(
            own == Some(new),
            "Uploaded macro metadata/data readback differs"
        );
    }
    if let Some(entry) = own {
        ensure!(
            entry.data.len() == new.data.len(),
            "New macro allocation size differs; cleanup cannot establish ownership"
        );
    }
    Ok(own.is_some())
}

fn target_mut(state: &mut layers::LayerReadback, layer: u8, button: u8) -> &mut Button {
    let bank = if layer == 0 {
        state
            .normal
            .buttons
            .iter_mut()
            .chain(&mut state.normal.controls)
    } else {
        state
            .hypershift
            .buttons
            .iter_mut()
            .chain(&mut state.hypershift.controls)
    };
    bank.into_iter().find(|b| b.button == button).unwrap()
}

impl<T: Transport> Mouse<T> {
    pub fn prepare_macro_backup(&mut self, backup: Backup) -> Result<Prepared> {
        let plan = backup.plan()?;
        self.check_macro_backup(&backup)?;
        Ok(Prepared { backup, plan })
    }

    pub fn prepare_macro(
        &mut self,
        known: &macros::Inspection,
        config: String,
        request: macro_plan::Request,
    ) -> Result<Prepared> {
        let active = known
            .mappings
            .iter()
            .find(|m| m.normal.slot == known.guard.active)
            .context("Missing active macro slot")?;
        let mappings = self.capture_layer_backup(active)?;
        let backup = Backup {
            format: 1,
            kind: "onboard_macro_transaction_backup".into(),
            complete_profile: false,
            contents: macros::Checkpoint::from_inspection(known.clone())?,
            mappings,
            config,
            request,
        };
        let plan = backup.plan()?;
        self.check_macro_backup(&backup)?;
        Ok(Prepared { backup, plan })
    }

    fn check_macro_backup(&mut self, backup: &Backup) -> Result<()> {
        let fresh = self.inspect_macros()?;
        backup.contents.check_fresh(&fresh)?;
        // inspect_macros already verifies every paired mapping repeatedly. Reuse
        // that exact readback instead of starting another full bank sweep; middle
        // click is deliberately absent from layer readbacks and still needs a read.
        ensure!(
            backup.mappings.slots.len() == fresh.mappings.len(),
            "Incomplete macro mapping backup"
        );
        for slot in &backup.mappings.slots {
            ensure!(
                fresh.mappings.iter().any(|mapping| mapping == &slot.state)
                    && self.get_button(slot.state.normal.slot, 3, 3)? == slot.middle,
                "Paired-bank state changed; no settings were written"
            );
        }
        Ok(())
    }

    fn check_macro_scope(
        &mut self,
        backup: &Backup,
        plan: &macro_plan::Plan,
        fresh: &macros::Inspection,
        bound: bool,
        recovering: bool,
    ) -> Result<()> {
        ensure!(
            fresh.guard == backup.contents.inspection.guard,
            "Mouse identity, slot or plate changed"
        );
        let mut expected = backup.contents.inspection.mappings.clone();
        if bound || recovering {
            let expected_target = expected
                .iter_mut()
                .find(|m| m.normal.slot == fresh.guard.active)
                .unwrap();
            let observed = fresh
                .mappings
                .iter()
                .find(|m| m.normal.slot == fresh.guard.active)
                .context("Active mappings missing")?;
            let mut observed = observed.clone();
            for layer in 0..=1 {
                if !recovering && layer != plan.request.layer {
                    continue;
                }
                let current = target_mut(&mut observed, layer, plan.request.button).clone();
                let original = target_mut(expected_target, layer, plan.request.button).clone();
                ensure!(
                    current.same_action(&plan.proposed_binding)
                        || recovering && current == original,
                    "Target binding changed outside the macro transaction"
                );
                *target_mut(expected_target, layer, plan.request.button) = current;
            }
            for (saved, current) in expected_target
                .normal_echoes
                .iter_mut()
                .zip(&observed.normal_echoes)
                .chain(
                    expected_target
                        .hypershift
                        .echoes
                        .iter_mut()
                        .zip(&observed.hypershift.echoes),
                )
            {
                if saved.button == plan.request.button {
                    ensure!(
                        recovering || current.layer == plan.request.layer,
                        "Macro target selector echo changed unexpectedly"
                    );
                    saved.layer = current.layer;
                }
            }
        }
        ensure!(
            fresh.mappings == expected,
            "Unrelated paired mappings changed; no restoration attempted"
        );
        for slot in &backup.mappings.slots {
            ensure!(
                self.get_button(slot.state.normal.slot, 3, 3)? == slot.middle,
                "Middle click changed"
            );
        }
        Ok(())
    }

    // Recovery only writes original records. A generic save rollback could
    // reinstall the uploaded binding when a restoration acknowledgement fails.
    fn restore_macro_bindings(&mut self, backup: &Backup, plan: &macro_plan::Plan) -> Result<()> {
        let slot = backup.contents.inspection.guard.active;
        let mut original = backup
            .contents
            .inspection
            .mappings
            .iter()
            .find(|m| m.normal.slot == slot)
            .context("Active mappings missing")?
            .clone();
        for layer in [1, 0] {
            let mut current = self.read_layers(Some(slot))?;
            let wanted = target_mut(&mut original, layer, plan.request.button).clone();
            if target_mut(&mut current, layer, plan.request.button) != &wanted {
                ensure!(
                    self.haptic_guard()? == backup.contents.inspection.guard,
                    "Mouse changed during macro restoration"
                );
                let acknowledgement = self.write_layer_record(slot, layer, &wanted);
                let mut after = self.read_layers(Some(slot))?;
                if target_mut(&mut after, layer, plan.request.button) != &wanted {
                    acknowledgement?;
                    bail!("Original macro target restoration did not read back exactly");
                }
            }
        }
        let wanted_echo = original
            .normal_echoes
            .iter()
            .find(|e| e.button == plan.request.button)
            .unwrap()
            .layer;
        let current = self.read_layers(Some(slot))?;
        if current.normal_echoes != original.normal_echoes
            || current.hypershift.echoes != original.hypershift.echoes
        {
            ensure!(
                self.haptic_guard()? == backup.contents.inspection.guard,
                "Mouse changed during macro restoration"
            );
            let wanted = target_mut(&mut original, wanted_echo, plan.request.button).clone();
            let acknowledgement = self.write_layer_record(slot, wanted_echo, &wanted);
            if let Err(error) = self.check_layer_backup(&backup.mappings) {
                acknowledgement?;
                return Err(error);
            }
        }
        self.check_layer_backup(&backup.mappings)?;
        Ok(())
    }

    /// The caller must have durably saved backup before acknowledging commit.
    /// The helper creates its own exclusive, fsynced ownership journal as well.
    pub fn commit_macro(&mut self, prepared: Prepared, path: &Path) -> Result<macros::Inspection> {
        let Prepared { backup, plan } = prepared;
        let mut journal = Journal::create(path, &backup)?;
        self.check_macro_backup(&backup)?;
        let mut progress = Progress::default();
        let result = (|| -> Result<macros::Inspection> {
            for (index, packet) in plan.upload.iter().enumerate() {
                ensure!(
                    self.haptic_guard()? == backup.contents.inspection.guard,
                    "Mouse state changed before macro upload"
                );
                journal.record(&Event::PacketPending { index })?;
                progress.attempted = true;
                // Only independently generated fresh-ID packets reach here.
                self.transport
                    .exchange(packet.class, packet.command, &packet.payload, 0)?;
                journal.record(&Event::PacketAcknowledged { index })?;
                progress.identified |= index >= 1;
            }
            let fresh = self.inspect_macros()?;
            unchanged_storage(
                &backup.contents.inspection.storage,
                &fresh.storage,
                &plan.entry,
                true,
            )?;
            self.check_macro_scope(&backup, &plan, &fresh, false, false)?;
            journal.record(&Event::BindingPending)?;
            self.write_layer_record(
                fresh.guard.active,
                plan.request.layer,
                &plan.proposed_binding,
            )?;
            let after = self.inspect_macros()?;
            unchanged_storage(
                &backup.contents.inspection.storage,
                &after.storage,
                &plan.entry,
                true,
            )?;
            self.check_macro_scope(&backup, &plan, &after, true, false)?;
            journal.record(&Event::Saved)?;
            Ok(after)
        })();
        match result {
            Ok(after) => Ok(after),
            Err(error) if progress.attempted => {
                self.recover_macro_inner(&backup, &plan, &mut journal, progress)
                    .with_context(|| {
                        format!(
                            "Macro save failed ({error:#}); recovery incomplete. Keep journal {}",
                            path.display()
                        )
                    })?;
                bail!(
                    "Macro save failed ({error:#}); original contents and scoped mappings restored. Journal: {}",
                    path.display()
                )
            }
            Err(error) => Err(error),
        }
    }

    pub fn recover_macro(&mut self, path: &Path) -> Result<macros::Inspection> {
        let (mut journal, saved, progress) = Journal::open(path)?;
        let fresh = self.inspect_macros()?;
        let backup = saved.at_path(&fresh.guard.device.path);
        let plan = backup.plan()?;
        self.recover_macro_inner(&backup, &plan, &mut journal, progress)
    }

    fn recover_macro_inner(
        &mut self,
        backup: &Backup,
        plan: &macro_plan::Plan,
        journal: &mut Journal,
        progress: Progress,
    ) -> Result<macros::Inspection> {
        let fresh = self.inspect_macros()?;
        if progress.complete {
            self.check_macro_scope(backup, plan, &fresh, false, false)?;
            ensure!(
                !unchanged_storage(
                    &backup.contents.inspection.storage,
                    &fresh.storage,
                    &plan.entry,
                    false
                )?,
                "A new allocation appeared after completed recovery"
            );
            return Ok(fresh);
        }
        if !progress.attempted {
            self.check_macro_backup(backup)?;
            journal.record(&Event::Recovering)?;
            journal.record(&Event::Recovered)?;
            return Ok(fresh);
        }
        self.check_macro_scope(backup, plan, &fresh, false, true)?;
        let allocated = unchanged_storage(
            &backup.contents.inspection.storage,
            &fresh.storage,
            &plan.entry,
            false,
        )?;
        if progress.identified
            && let Some(entry) = fresh.storage.entries.iter().find(|e| e.id == plan.entry.id)
        {
            ensure!(
                entry.metadata[..16] == plan.entry.metadata[..16],
                "Macro GUID changed after upload; allocation ownership is ambiguous"
            );
        }
        let journal_error = journal.record(&Event::Recovering).err();
        // Restore references before removing any allocation. A failed mapping
        // acknowledgement may already have landed; paired recovery rereads it.
        self.restore_macro_bindings(backup, plan)?;
        if let Some(error) = journal_error {
            bail!(
                "Original mappings restored, but journal update failed ({error:#}); allocation retained"
            );
        }
        let before_remove = self.inspect_macros()?;
        self.check_macro_scope(backup, plan, &before_remove, false, false)?;
        ensure!(
            !macro_plan::references(&before_remove)?
                .iter()
                .any(|r| r.id == plan.entry.id),
            "Macro allocation is still referenced; cleanup refused"
        );
        let still_allocated = unchanged_storage(
            &backup.contents.inspection.storage,
            &before_remove.storage,
            &plan.entry,
            false,
        )?;
        ensure!(
            allocated == still_allocated,
            "Macro inventory changed during recovery"
        );
        if allocated {
            journal.record(&Event::RemovalPending)?;
            let acknowledgement = self
                .transport
                .exchange(6, 3, &plan.entry.id.to_be_bytes(), 0);
            let after = self.inspect_macros()?;
            ensure!(
                !unchanged_storage(
                    &backup.contents.inspection.storage,
                    &after.storage,
                    &plan.entry,
                    false
                )?,
                "Owned macro allocation remains after cleanup"
            );
            self.check_macro_scope(backup, plan, &after, false, false)?;
            // A lost delete acknowledgement is resolved by a complete fresh
            // inventory/content read. The deletion is never blindly repeated.
            drop(acknowledgement);
        }
        let after = self.inspect_macros()?;
        ensure!(
            !unchanged_storage(
                &backup.contents.inspection.storage,
                &after.storage,
                &plan.entry,
                false
            )?,
            "Macro allocation cleanup incomplete"
        );
        self.check_macro_scope(backup, plan, &after, false, false)?;
        journal.record(&Event::Recovered)?;
        Ok(after)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{collections::BTreeMap, os::unix::fs::PermissionsExt, path::PathBuf};

    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
            let n = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let p =
                std::env::temp_dir().join(format!("nagalibre-macro-{}-{n}", std::process::id()));
            std::fs::create_dir(&p).unwrap();
            std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o700)).unwrap();
            Self(p)
        }
        fn journal(&self) -> PathBuf {
            self.0.join("transaction.jsonl")
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    struct Fake {
        mappings: BTreeMap<(u8, u8, u8), [u8; 7]>,
        echoes: BTreeMap<(u8, u8), u8>,
        macros: BTreeMap<u16, macros::Entry>,
        writes: Vec<(u8, u8, Vec<u8>)>,
        getters: usize,
        failures: BTreeSet<usize>,
        fail_before: bool,
        allocations: usize,
        alias_secondary: bool,
        corrupt_upload: bool,
        corrupt_old: bool,
        path: String,
    }

    impl Fake {
        fn new() -> Self {
            let mut mappings = BTreeMap::new();
            for slot in [1, 2] {
                for layer in [0, 1] {
                    for wire in [1, 2, 3, 0x34, 0x35, 0x6d, 0x60]
                        .into_iter()
                        .chain(0x40..=0x4b)
                    {
                        let record = if wire <= 3 {
                            [1, 1, wire, 0, 0, 0, 0]
                        } else {
                            [2, 1, 0, 0x1e, 0xaa, 0xbb, 0xcc]
                        };
                        mappings.insert((slot, layer, wire), record);
                    }
                }
            }
            Self {
                mappings,
                echoes: BTreeMap::new(),
                macros: BTreeMap::from([(
                    99,
                    macros::Entry {
                        id: 99,
                        metadata: vec![0xab; 250],
                        data: vec![0xfe, 0x99],
                    },
                )]),
                writes: vec![],
                getters: 0,
                failures: BTreeSet::new(),
                fail_before: false,
                allocations: 0,
                alias_secondary: false,
                corrupt_upload: false,
                corrupt_old: false,
                path: "mock".into(),
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
            let writing = command & 0x80 == 0;
            if !writing {
                self.getters += 1;
            }
            let failing = if writing {
                self.writes.push((class, command, p.to_vec()));
                self.failures.remove(&self.writes.len())
            } else {
                false
            };
            if failing && self.fail_before {
                bail!("Injected pre-write failure");
            }
            let mut response = p.to_vec();
            match (class, command) {
                (0, 0x82) => {
                    response = vec![0; 22];
                    response[..4].copy_from_slice(b"TEST");
                }
                (0, 0x84) => response = vec![0, 0],
                (0, 0xb9) => response = vec![3],
                (5, 0x81) => response = vec![5, 1, 2],
                (5, 0x84) => response = vec![1, 0, 0, 0, 0, 0],
                (2, 0x8c) => {
                    let record = self
                        .mappings
                        .get(&(p[0], p[2], p[1]))
                        .context("Unexpected mapping address")?;
                    response[2] = *self.echoes.get(&(p[0], p[1])).unwrap_or(&0);
                    response[3..].copy_from_slice(record);
                }
                (2, 0x0c) => {
                    ensure!(
                        [0x34, 0x35, 0x6d, 0x60].contains(&p[1]) || (0x40..=0x4b).contains(&p[1]),
                        "Primary or unknown mapping write"
                    );
                    self.mappings.insert((p[0], p[2], p[1]), p[3..].try_into()?);
                    self.echoes.insert((p[0], p[1]), p[2]);
                    if self.alias_secondary && p[2] == 1 {
                        self.mappings.insert((p[0], 0, p[1]), p[3..].try_into()?);
                    }
                }
                (6, 0x8e) => {
                    response = 100u16.to_be_bytes().to_vec();
                    for n in [
                        126976u32,
                        125696 - self.allocations as u32 * 512,
                        1024 + (self.allocations - self.macros.len().saturating_sub(1)) as u32
                            * 512,
                    ] {
                        response.extend(n.to_be_bytes());
                    }
                }
                (6, 0x80) => response = (self.macros.len() as u16).to_be_bytes().to_vec(),
                (6, 0x8b) => {
                    let offset = u16::from_be_bytes(p[..2].try_into()?) as usize;
                    let n = (p.len() - 4) / 2;
                    response[2..4].copy_from_slice(&(n as u16).to_be_bytes());
                    for (out, id) in response[4..]
                        .as_chunks_mut::<2>()
                        .0
                        .iter_mut()
                        .zip(self.macros.keys().skip(offset))
                    {
                        out.copy_from_slice(&id.to_be_bytes());
                    }
                }
                (6, 0x88) => {
                    let id = u16::from_be_bytes(p[..2].try_into()?);
                    response[2..6]
                        .copy_from_slice(&(self.macros[&id].data.len() as u32).to_be_bytes());
                }
                (6, 0x8c) => {
                    let id = u16::from_be_bytes(p[..2].try_into()?);
                    let offset = u16::from_be_bytes(p[2..4].try_into()?) as usize;
                    response[4..6].copy_from_slice(&250u16.to_be_bytes());
                    response[6..]
                        .copy_from_slice(&self.macros[&id].metadata[offset..offset + p.len() - 6]);
                }
                (6, 0x89) => {
                    let id = u16::from_be_bytes(p[..2].try_into()?);
                    let offset = u32::from_be_bytes(p[2..6].try_into()?) as usize;
                    response[7..].copy_from_slice(
                        &self.macros[&id].data[offset..offset + usize::from(p[6])],
                    );
                }
                (6, 8) => {
                    let id = u16::from_be_bytes(p[..2].try_into()?);
                    ensure!(
                        !self.macros.contains_key(&id),
                        "Attempt to overwrite an existing macro"
                    );
                    let size = u32::from_be_bytes(p[2..].try_into()?) as usize;
                    self.macros.insert(
                        id,
                        macros::Entry {
                            id,
                            metadata: vec![0; 250],
                            data: vec![0; size],
                        },
                    );
                    self.allocations += 1;
                }
                (6, 12) => {
                    let id = u16::from_be_bytes(p[..2].try_into()?);
                    ensure!(id != 99, "Existing metadata write");
                    let offset = u16::from_be_bytes(p[2..4].try_into()?) as usize;
                    self.macros.get_mut(&id).unwrap().metadata[offset..offset + p.len() - 6]
                        .copy_from_slice(&p[6..]);
                }
                (6, 9) => {
                    let id = u16::from_be_bytes(p[..2].try_into()?);
                    ensure!(id != 99, "Existing data write");
                    let offset = u32::from_be_bytes(p[2..6].try_into()?) as usize;
                    self.macros.get_mut(&id).unwrap().data[offset..offset + p.len() - 7]
                        .copy_from_slice(&p[7..]);
                    if self.corrupt_upload {
                        self.macros.get_mut(&id).unwrap().data[0] ^= 1;
                    }
                    if self.corrupt_old {
                        self.macros.get_mut(&99).unwrap().data[0] ^= 1;
                    }
                }
                (6, 3) => {
                    let id = u16::from_be_bytes(p.try_into()?);
                    ensure!(id != 99, "Deletion of existing macro");
                    self.macros.remove(&id);
                }
                _ => bail!("Unexpected macro transaction request {class:02x}/{command:02x}"),
            }
            if failing {
                bail!("Injected lost acknowledgement");
            }
            Ok(response)
        }
    }

    fn config() -> String {
        "[[binding]]\ntrigger='KEY_1'\nsteps=[{tap='KEY_B'}]".into()
    }
    fn request(layer: u8) -> macro_plan::Request {
        macro_plan::Request {
            trigger: "KEY_1".into(),
            guid: "00000000-0000-0000-0000-000000000001".into(),
            name: "Trial".into(),
            button: 1,
            layer,
            playback: macro_plan::Playback::Once {},
        }
    }
    fn prepared(mouse: &mut Mouse<Fake>, layer: u8) -> Result<Prepared> {
        let known = mouse.preview_macros()?;
        mouse.prepare_macro(&known, config(), request(layer))
    }
    fn original(
        mouse: &Mouse<Fake>,
        mappings: &BTreeMap<(u8, u8, u8), [u8; 7]>,
        old: &BTreeMap<u16, macros::Entry>,
    ) {
        assert_eq!(&mouse.transport.mappings, mappings);
        assert_eq!(&mouse.transport.macros, old);
        assert!(mouse.transport.echoes.values().all(|v| *v == 0));
    }

    #[test]
    fn transaction_getter_budgets() -> Result<()> {
        let mut m = Mouse {
            transport: Fake::new(),
        };
        let view = m.preview_macros()?;
        let start = m.transport.getters;
        m.capture_layer_backup(&view.mappings[0])?;
        let backup = m.transport.getters - start;
        let start = m.transport.getters;
        let plan = m.prepare_macro(&view, config(), request(0))?;
        let prepare = m.transport.getters - start;
        let temp = Temp::new();
        let start = m.transport.getters;
        m.commit_macro(plan, &temp.journal())?;
        let commit = m.transport.getters - start;
        let start = m.transport.getters;
        m.recover_macro(&temp.journal())?;
        let recovery = m.transport.getters - start;
        eprintln!(
            "Getter budgets: paired backup={backup}, macro prepare={prepare}, commit={commit}, recovery={recovery}"
        );
        // Two initialized slots, one existing short macro. Before removing
        // nested double reads these were 316 / 663 / 1095 / 2244.
        assert!(backup <= 170, "Paired backup getter budget: {backup}");
        assert!(prepare <= 370, "Macro prepare getter budget: {prepare}");
        assert!(commit <= 650, "Macro commit getter budget: {commit}");
        assert!(recovery <= 1500, "Macro recovery getter budget: {recovery}");
        Ok(())
    }

    #[test]
    fn compared_passes_reject_raw_mapping_and_middle_changes_without_writes() -> Result<()> {
        struct Changing {
            inner: Fake,
            address: (u8, u8, u8),
            reads: usize,
        }
        impl Transport for Changing {
            fn identity(&self) -> Identity {
                self.inner.identity()
            }
            fn exchange(
                &mut self,
                class: u8,
                command: u8,
                p: &[u8],
                echo: usize,
            ) -> Result<Vec<u8>> {
                if (class, command) == (2, 0x8c) && (p[0], p[2], p[1]) == self.address {
                    self.reads += 1;
                    if self.reads == 2 {
                        // Alter an opaque trailing byte, keeping the decoded
                        // action unchanged. Recovery requires exact records.
                        self.inner.mappings.get_mut(&self.address).unwrap()[6] ^= 1;
                    }
                }
                self.inner.exchange(class, command, p, echo)
            }
        }
        for address in [(1, 0, 0x40), (2, 1, 0x41), (2, 0, 3), (1, 0, 1)] {
            for inspection in [false, true] {
                // Macro mapping inspection deliberately excludes middle click;
                // backup capture and commit freshness check it independently.
                if inspection && address.2 == 3 {
                    continue;
                }
                let mut base = Mouse {
                    transport: Fake::new(),
                };
                let view = base.preview_macros()?;
                let mut mouse = Mouse {
                    transport: Changing {
                        inner: base.transport,
                        address,
                        reads: 0,
                    },
                };
                if inspection {
                    assert!(mouse.inspect_macros().is_err(), "{address:?}");
                } else {
                    assert!(
                        mouse.capture_layer_backup(&view.mappings[0]).is_err(),
                        "{address:?}"
                    );
                }
                assert!(mouse.transport.inner.writes.is_empty());
            }
        }
        Ok(())
    }

    #[test]
    fn macro_freshness_reuses_verified_bank_readback_and_still_checks_middle_click() -> Result<()> {
        let mut m = Mouse {
            transport: Fake::new(),
        };
        let plan = prepared(&mut m, 0)?;
        let start = m.transport.getters;
        m.inspect_macros()?;
        m.check_layer_backup(&plan.backup.mappings)?;
        let old = m.transport.getters - start;
        let start = m.transport.getters;
        m.check_macro_backup(&plan.backup)?;
        let current = m.transport.getters - start;
        assert!(current < old);
        eprintln!("Macro freshness getters: {old} -> {current}");
        m.transport.mappings.get_mut(&(2, 0, 3)).unwrap()[2] = 2;
        assert!(m.check_macro_backup(&plan.backup).is_err());
        assert!(m.transport.writes.is_empty());
        Ok(())
    }

    #[test]
    fn changed_display_view_cannot_prepare_a_macro_write() -> Result<()> {
        for mapping in [false, true] {
            let mut m = Mouse {
                transport: Fake::new(),
            };
            let view = m.preview_macros()?;
            if mapping {
                m.transport.mappings.get_mut(&(2, 1, 0x41)).unwrap()[3] ^= 1;
            } else {
                m.transport.macros.get_mut(&99).unwrap().data.push(0x77);
            }
            assert!(m.prepare_macro(&view, config(), request(0)).is_err());
            assert!(m.transport.writes.is_empty());
        }
        Ok(())
    }

    #[test]
    fn fresh_upload_verified_before_binding_and_exact_owned_recovery_is_idempotent() -> Result<()> {
        for layer in [0, 1] {
            let temp = Temp::new();
            let mut m = Mouse {
                transport: Fake::new(),
            };
            let mappings = m.transport.mappings.clone();
            let old = m.transport.macros.clone();
            let p = prepared(&mut m, layer)?;
            let after = m.commit_macro(p, &temp.journal())?;
            assert_eq!(after.storage.stored_count, 2);
            let writes = &m.transport.writes;
            assert_eq!(
                writes.iter().map(|(c, k, _)| (*c, *k)).collect::<Vec<_>>(),
                [(6, 8), (6, 12), (6, 12), (6, 12), (6, 12), (6, 9), (2, 12)]
            );
            assert_eq!(std::fs::metadata(temp.journal())?.mode() & 0o777, 0o600);
            m.transport.path = "reconnected".into();
            let restored = m.recover_macro(&temp.journal())?;
            original(&m, &mappings, &old);
            assert_eq!(restored.storage.entries.len(), 1);
            assert_ne!(restored.storage.reclaimable_bytes, 1024); // contents, not flash accounting
            let n = m.transport.writes.len();
            m.recover_macro(&temp.journal())?;
            assert_eq!(m.transport.writes.len(), n);
        }
        Ok(())
    }

    #[test]
    fn each_failed_or_lost_upload_and_binding_ack_rolls_back_only_owned_changes() -> Result<()> {
        for fail_before in [false, true] {
            for layer in [0, 1] {
                for failure in 1..=7 {
                    let temp = Temp::new();
                    let mut m = Mouse {
                        transport: Fake::new(),
                    };
                    let mappings = m.transport.mappings.clone();
                    let old = m.transport.macros.clone();
                    let p = prepared(&mut m, layer)?;
                    m.transport.fail_before = fail_before;
                    m.transport.failures.insert(failure);
                    let result = m.commit_macro(p, &temp.journal());
                    assert!(result.is_err(), "accepted failure {failure}");
                    original(&m, &mappings, &old);
                    assert!(format!("{:#}", result.unwrap_err()).contains("restored"));
                    m.recover_macro(&temp.journal())?;
                }
            }
        }
        Ok(())
    }

    #[test]
    fn interrupted_packet_intent_recovers_without_replaying_allocation_or_upload() -> Result<()> {
        for stop in 0..=6 {
            for pending_landed in [false, true] {
                let temp = Temp::new();
                let mut m = Mouse {
                    transport: Fake::new(),
                };
                let mappings = m.transport.mappings.clone();
                let old = m.transport.macros.clone();
                let p = prepared(&mut m, 1)?;
                let mut journal = Journal::create(&temp.journal(), p.backup())?;
                for (index, packet) in p.plan.upload.iter().enumerate() {
                    if index == stop {
                        journal.record(&Event::PacketPending { index })?;
                        if pending_landed {
                            m.transport.exchange(
                                packet.class,
                                packet.command,
                                &packet.payload,
                                0,
                            )?;
                        }
                        break;
                    }
                    journal.record(&Event::PacketPending { index })?;
                    m.transport
                        .exchange(packet.class, packet.command, &packet.payload, 0)?;
                    journal.record(&Event::PacketAcknowledged { index })?;
                }
                if stop == 6 {
                    journal.record(&Event::BindingPending)?;
                    if pending_landed {
                        m.write_layer_record(1, 1, &p.plan.proposed_binding)?;
                    }
                }
                drop(journal);
                let n = m.transport.writes.len();
                m.recover_macro(&temp.journal())?;
                original(&m, &mappings, &old);
                assert!(
                    m.transport.writes[n..]
                        .iter()
                        .all(|(c, k, _)| *c == 2 || (*c, *k) == (6, 3))
                );
            }
        }
        Ok(())
    }

    #[test]
    fn stale_or_failed_journal_cannot_mutate_and_opaque_old_contents_are_preserved() -> Result<()> {
        for which in 0..4 {
            let temp = Temp::new();
            let mut m = Mouse {
                transport: Fake::new(),
            };
            let p = prepared(&mut m, 0)?;
            let path = if which == 0 {
                temp.0.join("missing/txn")
            } else {
                temp.journal()
            };
            if which == 1 {
                std::fs::write(&path, b"existing")?;
            }
            if which == 2 {
                m.transport.macros.get_mut(&99).unwrap().data.push(0x77);
            }
            if which == 3 {
                m.transport.mappings.get_mut(&(2, 1, 0x41)).unwrap()[3] ^= 1;
            }
            assert!(m.commit_macro(p, &path).is_err());
            assert!(m.transport.writes.is_empty());
        }
        Ok(())
    }

    #[test]
    fn corrupt_uploaded_data_never_binds_and_unrelated_change_prevents_cleanup() -> Result<()> {
        for old_corruption in [false, true] {
            let temp = Temp::new();
            let mut m = Mouse {
                transport: Fake::new(),
            };
            let mappings = m.transport.mappings.clone();
            let old = m.transport.macros.clone();
            let p = prepared(&mut m, 0)?;
            m.transport.corrupt_upload = !old_corruption;
            m.transport.corrupt_old = old_corruption;
            assert!(m.commit_macro(p, &temp.journal()).is_err());
            assert!(m.transport.writes.iter().all(|(c, _, _)| *c != 2));
            if old_corruption {
                assert_eq!(m.transport.macros.len(), 2);
                assert!(
                    !m.transport
                        .writes
                        .iter()
                        .any(|(c, k, _)| (*c, *k) == (6, 3))
                );
            } else {
                original(&m, &mappings, &old);
            }
        }
        Ok(())
    }

    #[test]
    fn recovery_refuses_new_shared_references_and_foreign_guid_then_can_resume() -> Result<()> {
        for foreign_guid in [false, true] {
            let temp = Temp::new();
            let mut m = Mouse {
                transport: Fake::new(),
            };
            let mappings = m.transport.mappings.clone();
            let old = m.transport.macros.clone();
            let p = prepared(&mut m, 0)?;
            let id = p.plan.entry.id;
            m.commit_macro(p, &temp.journal())?;
            let original_metadata = m.transport.macros[&id].metadata.clone();
            if foreign_guid {
                m.transport.macros.get_mut(&id).unwrap().metadata[0] ^= 1;
            } else {
                m.transport
                    .mappings
                    .insert((2, 1, 0x41), [3, 3, (id >> 8) as u8, id as u8, 1, 0, 0]);
            }
            let n = m.transport.writes.len();
            assert!(m.recover_macro(&temp.journal()).is_err());
            assert_eq!(m.transport.writes.len(), n);
            m.transport.macros.get_mut(&id).unwrap().metadata = original_metadata;
            if !foreign_guid {
                m.transport
                    .mappings
                    .insert((2, 1, 0x41), mappings[&(2, 1, 0x41)]);
            }
            m.recover_macro(&temp.journal())?;
            original(&m, &mappings, &old);
        }
        Ok(())
    }

    #[test]
    fn truncated_tail_and_lost_delete_ack_are_resolved_by_inventory_readback() -> Result<()> {
        let temp = Temp::new();
        let mut m = Mouse {
            transport: Fake::new(),
        };
        let p = prepared(&mut m, 0)?;
        m.commit_macro(p, &temp.journal())?;
        OpenOptions::new()
            .append(true)
            .open(temp.journal())?
            .write_all(b"{\"event\":\"recov")?;
        let n = m.transport.writes.len();
        // One mapping restore precedes deletion for a normal-bank binding.
        m.transport.failures.insert(n + 2);
        m.recover_macro(&temp.journal())?;
        assert_eq!(m.transport.macros.len(), 1);
        assert!(std::fs::read_to_string(temp.journal())?.ends_with("\n"));
        Ok(())
    }

    #[test]
    fn restoration_failures_never_reinstall_uploaded_binding_and_retry_is_safe() -> Result<()> {
        for layer in [0, 1] {
            for fail_before in [false, true] {
                let temp = Temp::new();
                let mut m = Mouse {
                    transport: Fake::new(),
                };
                let mappings = m.transport.mappings.clone();
                let old = m.transport.macros.clone();
                let p = prepared(&mut m, layer)?;
                m.commit_macro(p, &temp.journal())?;
                let n = m.transport.writes.len();
                m.transport.fail_before = fail_before;
                m.transport.failures.insert(n + 1);
                let result = m.recover_macro(&temp.journal());
                if fail_before {
                    assert!(result.is_err());
                    assert_eq!(m.transport.macros.len(), 2);
                } else {
                    result?;
                }
                for (class, command, payload) in &m.transport.writes[n..] {
                    if (*class, *command) == (2, 12) {
                        assert_eq!(
                            &payload[3..],
                            &mappings[&(payload[0], payload[2], payload[1])]
                        );
                    }
                }
                m.recover_macro(&temp.journal())?;
                original(&m, &mappings, &old);
            }
        }
        Ok(())
    }

    #[test]
    fn interrupted_selector_echo_restoration_resumes_from_original_records() -> Result<()> {
        let temp = Temp::new();
        let mut m = Mouse {
            transport: Fake::new(),
        };
        m.transport.echoes.insert((1, 0x40), 1);
        let mappings = m.transport.mappings.clone();
        let old = m.transport.macros.clone();
        let p = prepared(&mut m, 0)?;
        m.commit_macro(p, &temp.journal())?;
        // Restore normal action, then fail before restoring its original shared echo.
        m.transport.fail_before = true;
        m.transport.failures.insert(m.transport.writes.len() + 2);
        assert!(m.recover_macro(&temp.journal()).is_err());
        assert_eq!(m.transport.mappings, mappings);
        assert_eq!(m.transport.macros.len(), 2);
        m.recover_macro(&temp.journal())?;
        assert_eq!(m.transport.mappings, mappings);
        assert_eq!(m.transport.macros, old);
        assert_eq!(m.transport.echoes[&(1, 0x40)], 1);
        Ok(())
    }

    #[test]
    fn unexpected_secondary_alias_is_restored_without_rebinding_macro() -> Result<()> {
        let temp = Temp::new();
        let mut m = Mouse {
            transport: Fake::new(),
        };
        let mappings = m.transport.mappings.clone();
        let old = m.transport.macros.clone();
        let p = prepared(&mut m, 1)?;
        m.transport.alias_secondary = true;
        assert!(m.commit_macro(p, &temp.journal()).is_err());
        original(&m, &mappings, &old);
        m.recover_macro(&temp.journal())?;
        Ok(())
    }

    #[test]
    fn journal_io_failure_restores_references_but_retains_allocation_for_reopen() -> Result<()> {
        let temp = Temp::new();
        let mut m = Mouse {
            transport: Fake::new(),
        };
        let mappings = m.transport.mappings.clone();
        let old = m.transport.macros.clone();
        let p = prepared(&mut m, 1)?;
        m.commit_macro(p, &temp.journal())?;
        let (mut journal, backup, progress) = Journal::open(&temp.journal())?;
        let plan = backup.plan()?;
        journal.file = File::open(temp.journal())?; // Force EBADF on append, including as root.
        let result = m.recover_macro_inner(&backup, &plan, &mut journal, progress);
        assert!(format!("{:#}", result.unwrap_err()).contains("allocation retained"));
        assert_eq!(m.transport.mappings, mappings);
        assert!(m.transport.echoes.values().all(|e| *e == 0));
        assert_eq!(m.transport.macros.len(), 2);
        assert!(journal.poisoned);
        assert!(journal.record(&Event::RemovalPending).is_err());
        drop(journal);
        m.recover_macro(&temp.journal())?;
        original(&m, &mappings, &old);
        Ok(())
    }

    #[test]
    fn journal_lock_permissions_symlink_and_invalid_event_order_fail_before_mutation() -> Result<()>
    {
        let temp = Temp::new();
        let mut m = Mouse {
            transport: Fake::new(),
        };
        let p = prepared(&mut m, 0)?;
        let mut j = Journal::create(&temp.journal(), p.backup())?;
        assert!(m.recover_macro(&temp.journal()).is_err());
        j.record(&Event::BindingPending)?;
        drop(j);
        assert!(m.recover_macro(&temp.journal()).is_err());
        std::fs::set_permissions(temp.journal(), std::fs::Permissions::from_mode(0o644))?;
        assert!(m.recover_macro(&temp.journal()).is_err());
        let link = temp.0.join("link");
        std::os::unix::fs::symlink(temp.journal(), &link)?;
        assert!(m.recover_macro(&link).is_err());
        assert!(m.transport.writes.is_empty());
        Ok(())
    }
}
