//! Diagnostic only: compare active stored-profile and selector-zero table reads.
//! Selector zero's direct pointer path is traced in both extracted firmware images.
use super::{
    haptic::{Record, finite, query},
    *,
};
use serde_json::{Value, json};

pub(super) fn table_prefix_overlap(tables: &[Vec<[u8; 8]>]) -> bool {
    tables.len() == 3 && !tables[2].is_empty() && tables[0].starts_with(&tables[2])
}

#[derive(Debug, Serialize)]
pub(super) struct IndependentStateMismatch {
    pub slot: u8,
    pub fields: Vec<String>,
    pub expected: Box<super::haptic::State>,
    pub observed: Box<super::haptic::State>,
}
impl IndependentStateMismatch {
    fn new(expected: &super::haptic::State, observed: super::haptic::State) -> Self {
        let mut fields = Vec::new();
        for (name, before, after) in [
            ("slot", json!(expected.slot), json!(observed.slot)),
            (
                "active_position",
                json!(expected.active_position),
                json!(observed.active_position),
            ),
            ("stages", json!(expected.stages), json!(observed.stages)),
            (
                "browsing_mode",
                json!(expected.browsing_mode),
                json!(observed.browsing_mode),
            ),
            (
                "capacities",
                json!(expected.capacities),
                json!(observed.capacities),
            ),
            (
                "configuration",
                json!(expected.configuration),
                json!(observed.configuration),
            ),
            (
                "metadata",
                json!(expected.metadata),
                json!(observed.metadata),
            ),
        ] {
            if before != after {
                fields.push(name.to_owned());
            }
        }
        if expected.tables.len() != observed.tables.len() {
            fields.push("table_count".into());
        }
        for (i, (before, after)) in expected.tables.iter().zip(&observed.tables).enumerate() {
            if before != after {
                fields.push(format!("tables[{i}]"));
            }
        }
        if expected.records.len() != observed.records.len() {
            fields.push("record_count".into());
        }
        for (i, (before, after)) in expected.records.iter().zip(&observed.records).enumerate() {
            if before != after {
                fields.push(format!("records[{i}] 15/{:02x}", after.command));
            }
        }
        Self {
            slot: expected.slot,
            fields,
            expected: Box::new(expected.clone()),
            observed: Box::new(observed),
        }
    }
}
impl std::fmt::Display for IndependentStateMismatch {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "Independent wheel state mismatch in slot {}: {}",
            self.slot,
            self.fields.join(", ")
        )
    }
}
impl std::error::Error for IndependentStateMismatch {}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct View {
    profile_selector: u8,
    capacities: [u16; 3],
    configuration: Vec<u8>,
    tables: Vec<Vec<[u8; 8]>>,
    records: Vec<Record>,
}

fn independent_state(mut state: super::haptic::State, live: View) -> super::haptic::State {
    state.tables = live.tables;
    state.records.retain(|r| r.command != 0x84);
    state
        .records
        .extend(live.records.into_iter().filter(|r| r.command == 0x84));
    state
}

pub(super) fn independent_replay_backup(
    value: &Value,
) -> Result<super::haptic_transaction::Backup> {
    ensure!(
        value["format"] == 1 && value["kind"] == "haptic_independent_checkpoint",
        "Independent upload requires its separate getter checkpoint"
    );
    let mut baseline: super::haptic_transaction::Backup =
        serde_json::from_value(value["baseline"].clone())?;
    let active = baseline
        .slots
        .iter_mut()
        .find(|s| s.slot == baseline.guard.active)
        .context("Independent checkpoint lacks active slot")?;
    let known = super::haptic::Inspection {
        format: 1,
        kind: "haptic_diagnostic".into(),
        guard: baseline.guard.clone(),
        state: active.clone(),
    };
    validate_independent_views(&known, &value["table_views"])?;
    let live: View = serde_json::from_value(value["table_views"]["live"].clone())?;
    *active = independent_state(active.clone(), live);
    // This derived representation stays internal. The durable outer checkpoint
    // and the journal's verification policy preserve its independent provenance.
    Ok(baseline)
}

impl<T: Transport> Mouse<T> {
    pub(super) fn check_independent_haptic_backup(
        &mut self,
        backup: &super::haptic_transaction::Backup,
    ) -> Result<()> {
        ensure!(
            backup.format == 1
                && backup.kind == "haptic_settings_backup"
                && backup.slots.iter().map(|s| s.slot).collect::<Vec<_>>() == backup.guard.slots,
            "Incomplete independent checkpoint"
        );
        ensure!(
            self.haptic_guard()? == backup.guard,
            "Independent checkpoint is stale"
        );
        self.check_layer_backup(&backup.mappings)?;
        for before in &backup.slots {
            let current = self.inspect_haptic(Some(before.slot))?;
            ensure!(
                current.guard == backup.guard,
                "Mouse changed during independent verification"
            );
            let state = if before.slot == backup.guard.active {
                let views = self.inspect_haptic_table_views()?;
                validate_independent_views(&current, &views)?;
                independent_state(
                    current.state,
                    serde_json::from_value(views["live"].clone())?,
                )
            } else {
                current.state
            };
            if state != *before {
                return Err(IndependentStateMismatch::new(before, state).into());
            }
        }
        ensure!(
            self.haptic_guard()? == backup.guard,
            "Mouse changed after independent verification"
        );
        Ok(())
    }

    /// Getter-only checkpoint for the active slot's independently addressed
    /// Custom tables. Deliberately incompatible with legacy upload backups.
    pub fn inspect_haptic_independent_checkpoint(&mut self) -> Result<Value> {
        let known = self.inspect_haptic(None)?;
        let prepared = self.prepare_haptic(
            &known,
            super::haptic_transaction::Edit {
                active_position: known.state.active_position,
                stages: known.state.stages.clone(),
            },
        )?;
        let views = self.inspect_haptic_table_views()?;
        validate_independent_views(&known, &views)?;
        self.check_haptic_backup(&prepared.backup)?;
        ensure!(
            self.inspect_haptic_table_views()? == views,
            "Independent table views changed while capturing checkpoint"
        );
        Ok(json!({
            "format":1,
            "kind":"haptic_independent_checkpoint",
            "baseline":prepared.backup,
            "table_views":views,
            "scope":"Getter-only checkpoint: selector-zero tables cover the currently active slot; inactive stored table getters may alias and inactive metadata may be unavailable. Legacy upload and stage-restore commands must not accept this format. No claim of pre-replay original table recovery."
        }))
    }

    fn custom_table_view(&mut self, profile: u8) -> Result<View> {
        let mut records = Vec::new();
        let caps = query(self, &mut records, 0x85, vec![0; 6], 0)?;
        ensure!(caps.len() == 6, "Invalid table-view capacity response");
        let capacities =
            std::array::from_fn(|i| u16::from_be_bytes([caps[i * 2], caps[i * 2 + 1]]));
        ensure!(
            capacities.iter().all(|n| *n <= 80),
            "Table-view capacity exceeds bounded firmware format"
        );
        let mut request = vec![0; 26];
        request[..2].copy_from_slice(&[profile, 6]);
        let configuration = query(self, &mut records, 0x83, request, 2)?;
        ensure!(
            configuration.len() == 26,
            "Invalid table-view configuration length"
        );
        finite(&configuration[4..20])?;
        let mut tables = Vec::new();
        for (t, capacity) in capacities.into_iter().enumerate() {
            let count = u16::from_be_bytes([configuration[20 + t * 2], configuration[21 + t * 2]]);
            ensure!(count <= capacity, "Table-view count exceeds capacity");
            let mut points = Vec::new();
            let mut start = 0u16;
            while start < count {
                let n = (count - start).min(8);
                let mut request = vec![0; 71];
                request[..3].copy_from_slice(&[profile, 6, t as u8 + 1]);
                request[3..5].copy_from_slice(&start.to_be_bytes());
                request[5..7].copy_from_slice(&n.to_be_bytes());
                let reply = query(self, &mut records, 0x84, request, 7)?;
                ensure!(reply.len() == 71, "Invalid table-view chunk length");
                finite(&reply[7..7 + usize::from(n) * 8])?;
                for p in reply[7..7 + usize::from(n) * 8].as_chunks::<8>().0 {
                    points.push(*p);
                }
                start += n;
            }
            tables.push(points);
        }
        Ok(View {
            profile_selector: profile,
            capacities,
            configuration,
            tables,
            records,
        })
    }

    pub fn inspect_haptic_table_views(&mut self) -> Result<Value> {
        let guard = self.haptic_guard()?;
        let stored = self.custom_table_view(guard.active)?;
        let live = self.custom_table_view(0)?;
        ensure!(
            self.haptic_guard()? == guard,
            "Mouse changed during table-view inspection"
        );
        ensure!(
            self.custom_table_view(guard.active)? == stored && self.custom_table_view(0)? == live,
            "Table views changed between repeated reads"
        );
        ensure!(
            self.haptic_guard()? == guard,
            "Mouse changed after table-view inspection"
        );
        let matches = stored
            .tables
            .iter()
            .zip(&live.tables)
            .map(|(a, b)| a == b)
            .collect::<Vec<_>>();
        Ok(
            json!({"format":1,"kind":"unverified_haptic_table_views","guard":guard,"stable":true,
            "stored_prefix_overlap":table_prefix_overlap(&stored.tables),
            "live_prefix_overlap":table_prefix_overlap(&live.tables),
            "stored_matches_live":matches,"stored":stored,"live":live,
            "scope":"Getter-only diagnostic; selector-zero provenance and persistent independent table recovery remain unverified"}),
        )
    }
}

fn validate_independent_views(known: &super::haptic::Inspection, views: &Value) -> Result<()> {
    ensure!(
        views["format"] == 1
            && views["kind"] == "unverified_haptic_table_views"
            && views["stable"] == true
            && views["guard"] == json!(known.guard),
        "Independent views belong to different device/state"
    );
    let stored = &views["stored"];
    let live = &views["live"];
    ensure!(
        stored["profile_selector"] == known.state.slot
            && live["profile_selector"] == 0
            && stored["configuration"] == json!(known.state.configuration)
            && stored["tables"] == json!(known.state.tables)
            && stored["capacities"] == json!(known.state.capacities)
            && live["capacities"] == stored["capacities"],
        "Stored table view differs from checkpoint"
    );
    let config = live["configuration"]
        .as_array()
        .context("Missing selector-zero configuration")?;
    let original = stored["configuration"]
        .as_array()
        .context("Missing stored configuration")?;
    let tables = live["tables"]
        .as_array()
        .context("Missing independent tables")?;
    ensure!(
        config.len() == 26
            && config[0] == 0
            && config[1..] == original[1..]
            && tables.len() == 3
            && tables[0] == stored["tables"][0],
        "Selector-zero configuration/CW does not correspond to active stored slot"
    );
    // Do not require CCW or velocity to match stored getters: the slot-2
    // hardware control proved those getters return aliased CW bytes. Also do
    // not reject a real prefix overlap in the zero view: slot 1 currently has
    // such data after the earlier replay, and a checkpoint must preserve it.
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Device {
        calls: Vec<(u8, u8, Vec<u8>)>,
        reject_live: bool,
        bad: u8,
        live_reads: usize,
    }
    impl Transport for Device {
        fn identity(&self) -> Identity {
            Identity {
                path: "mock".into(),
                product: 0xa7,
                serial: String::new(),
            }
        }
        fn exchange(&mut self, c: u8, cmd: u8, p: &[u8], _: usize) -> Result<Vec<u8>> {
            assert!(cmd >= 0x80, "No settings writes permitted");
            self.calls.push((c, cmd, p.to_vec()));
            if self.reject_live && c == 0x15 && cmd == 0x83 && p[0] == 0 {
                return Err(hidraw::Rejected {
                    class: c,
                    command: cmd,
                    status: 3,
                }
                .into());
            }
            Ok(match (c, cmd) {
                (0, 0x82) => {
                    let mut r = vec![0; 22];
                    r[0] = b'X';
                    r
                }
                (0, 0x84) => vec![0, 0],
                (5, 0x81) => vec![5, 1, 2],
                (5, 0x84) => vec![1, 0, 0, 0, 0, 0],
                (0, 0xb9) => vec![3],
                (0x15, 0x85) => {
                    if self.bad == 1 {
                        vec![0, 81, 0, 80, 0, 80]
                    } else {
                        vec![0, 80, 0, 80, 0, 80]
                    }
                }
                (0x15, 0x83) => {
                    if p[0] == 0 {
                        self.live_reads += 1;
                    }
                    let mut r = p.to_vec();
                    r[2] = 1;
                    r[3] = 1;
                    r[21] = if self.bad == 2 { 81 } else { 45 };
                    r[23] = 45;
                    r[25] = 3;
                    if self.bad == 3 && p[0] == 0 {
                        r[0] = 1;
                    }
                    r
                }
                (0x15, 0x84) => {
                    let mut r = p.to_vec();
                    let start = usize::from(u16::from_be_bytes([p[3], p[4]]));
                    let n = usize::from(u16::from_be_bytes([p[5], p[6]]));
                    for i in 0..n {
                        let (x, y) = if p[0] == 0 && p[2] == 3 {
                            ([-720f32, 0., 720.][start + i], 1f32)
                        } else {
                            (
                                (start + i) as f32,
                                if p[0] == 0 && p[2] == 2 {
                                    0.2f32
                                } else {
                                    0.1f32
                                },
                            )
                        };
                        r[7 + i * 8..11 + i * 8].copy_from_slice(&x.to_le_bytes());
                        r[11 + i * 8..15 + i * 8].copy_from_slice(&y.to_le_bytes());
                    }
                    if self.bad == 4 && p[0] == 0 {
                        r.truncate(70);
                    }
                    if self.bad == 5 && p[0] == 0 && self.live_reads > 1 {
                        r[7] ^= 1;
                    }
                    if self.bad == 6 && p[0] == 0 {
                        r[7..11].copy_from_slice(&f32::NAN.to_le_bytes());
                    }
                    r
                }
                _ => bail!("Unexpected getter {c:02x}/{cmd:02x}"),
            })
        }
    }
    fn mouse() -> Mouse<Device> {
        Mouse {
            transport: Device {
                calls: vec![],
                reject_live: false,
                bad: 0,
                live_reads: 0,
            },
        }
    }
    #[test]
    fn aliased_stored_views_and_independent_live_tables_are_reported_separately() {
        let mut m = mouse();
        let r = m.inspect_haptic_table_views().unwrap();
        assert_eq!(r["stored_prefix_overlap"], true);
        assert_eq!(r["live_prefix_overlap"], false);
        assert_eq!(r["stored_matches_live"], json!([true, false, false]));
        assert_eq!(r["kind"], "unverified_haptic_table_views");
        assert!(serde_json::from_value::<super::super::haptic_transaction::Backup>(r).is_err());
        for profile in [0, 1] {
            assert!(m.transport.calls.iter().any(|(c, cmd, p)| *c == 0x15
                && *cmd == 0x84
                && p[..7] == [profile, 6, 1, 0, 40, 0, 5]));
        }
    }
    #[test]
    fn rejected_live_getter_stops_without_other_selectors_or_fallback() {
        let mut m = mouse();
        m.transport.reject_live = true;
        assert!(
            m.inspect_haptic_table_views()
                .unwrap_err()
                .downcast_ref::<hidraw::Rejected>()
                .is_some()
        );
        assert_eq!(
            m.transport
                .calls
                .iter()
                .filter(|(c, cmd, p)| *c == 0x15 && *cmd == 0x83 && p[0] == 0)
                .count(),
            1
        );
    }
    #[test]
    fn bounded_reader_rejects_bad_caps_counts_echoes_lengths_unstable_and_nonfinite_values() {
        for bad in 1..=6 {
            let mut m = mouse();
            m.transport.bad = bad;
            assert!(m.inspect_haptic_table_views().is_err(), "fault {bad}");
            if bad <= 2 {
                assert!(
                    !m.transport
                        .calls
                        .iter()
                        .any(|(c, cmd, _)| *c == 0x15 && *cmd == 0x84)
                );
            }
        }
    }
    #[test]
    fn prefix_warning_requires_a_nonempty_velocity_table_and_exact_point_bytes() {
        let p = [0; 8];
        assert!(!table_prefix_overlap(&[vec![p], vec![p], vec![]]));
        assert!(table_prefix_overlap(&[vec![p], vec![p], vec![p]]));
        assert!(!table_prefix_overlap(&[vec![p], vec![p], vec![[1; 8]]]));
    }
}
