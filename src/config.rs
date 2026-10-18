use anyhow::{Context, Result, bail, ensure};
use evdev::KeyCode;
use serde::Deserialize;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
    str::FromStr,
};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    #[serde(default = "default_tap_ms")]
    tap_ms: u64,
    binding: Vec<Binding>,
}

fn default_tap_ms() -> u64 {
    20
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Binding {
    trigger: String,
    key: Option<String>,
    steps: Option<Vec<Step>>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Step {
    tap: Option<String>,
    chord: Option<Vec<String>>,
    down: Option<String>,
    up: Option<String>,
    wait_ms: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Action {
    pub at_ms: u64,
    pub key: KeyCode,
    pub pressed: bool,
}

#[derive(Debug)]
pub struct Macro {
    pub remap: Option<KeyCode>,
    pub actions: Vec<Action>,
    pub duration_ms: u64,
}

pub type Bindings = BTreeMap<KeyCode, Macro>;

fn key(name: &str) -> Result<KeyCode> {
    let key = KeyCode::from_str(name).with_context(|| {
        format!("Unknown Linux key code {name:?}; use names such as KEY_1 or BTN_SIDE")
    })?;
    ensure!(
        key != KeyCode::KEY_RESERVED && (name.starts_with("KEY_") || name.starts_with("BTN_")),
        "Invalid key {name}"
    );
    Ok(key)
}

pub fn load(path: &Path) -> Result<Bindings> {
    let text = fs::read_to_string(path).with_context(|| format!("Reading {}", path.display()))?;
    parse(&text)
}

pub fn parse(text: &str) -> Result<Bindings> {
    let config: Config = toml::from_str(text).context("Invalid macro TOML")?;
    ensure!(
        (1..=1000).contains(&config.tap_ms),
        "tap_ms must be between 1 and 1000"
    );
    let mut bindings = BTreeMap::new();
    for binding in config.binding {
        let trigger = key(&binding.trigger)?;
        ensure!(
            binding.key.is_some() != binding.steps.is_some(),
            "{} must have exactly one of key or steps",
            binding.trigger
        );
        if let Some(target) = binding.key {
            ensure!(
                bindings
                    .insert(
                        trigger,
                        Macro {
                            remap: Some(key(&target)?),
                            actions: Vec::new(),
                            duration_ms: 0
                        }
                    )
                    .is_none(),
                "Duplicate trigger {}",
                binding.trigger
            );
            continue;
        }
        let steps = binding.steps.unwrap();
        ensure!(!steps.is_empty(), "{} has no steps", binding.trigger);
        ensure!(steps.len() <= 4096, "Too many steps");
        let mut held = BTreeSet::new();
        let mut actions = Vec::new();
        let mut now = 0;
        for step in steps {
            let count = usize::from(step.tap.is_some())
                + usize::from(step.chord.is_some())
                + usize::from(step.down.is_some())
                + usize::from(step.up.is_some())
                + usize::from(step.wait_ms.is_some());
            ensure!(
                count == 1,
                "Each step must contain exactly one of tap, chord, down, up, wait_ms"
            );
            if let Some(delay) = step.wait_ms {
                ensure!(delay <= 60_000, "A wait must not exceed 60000ms");
                now += delay;
            } else if let Some(name) = step.down {
                let k = key(&name)?;
                ensure!(held.insert(k), "{name} is already held");
                actions.push(Action {
                    at_ms: now,
                    key: k,
                    pressed: true,
                });
            } else if let Some(name) = step.up {
                let k = key(&name)?;
                ensure!(held.remove(&k), "{name} was not held");
                actions.push(Action {
                    at_ms: now,
                    key: k,
                    pressed: false,
                });
            } else {
                let names = if let Some(name) = step.tap {
                    vec![name]
                } else {
                    step.chord.unwrap()
                };
                ensure!(!names.is_empty(), "A chord cannot be empty");
                let keys = names.iter().map(|n| key(n)).collect::<Result<Vec<_>>>()?;
                let mut unique = BTreeSet::new();
                for k in &keys {
                    ensure!(
                        !held.contains(k) && unique.insert(*k),
                        "Duplicate or already held key {k:?} in tap/chord"
                    );
                    actions.push(Action {
                        at_ms: now,
                        key: *k,
                        pressed: true,
                    });
                }
                now += config.tap_ms;
                for k in keys.iter().rev() {
                    actions.push(Action {
                        at_ms: now,
                        key: *k,
                        pressed: false,
                    });
                }
            }
            ensure!(now <= 300_000, "A macro must not exceed five minutes");
        }
        ensure!(
            held.is_empty(),
            "{} leaves keys held; add matching up steps",
            binding.trigger
        );
        ensure!(
            !actions.is_empty(),
            "{} contains no key actions",
            binding.trigger
        );
        if bindings
            .insert(
                trigger,
                Macro {
                    remap: None,
                    actions,
                    duration_ms: now,
                },
            )
            .is_some()
        {
            bail!("Duplicate trigger {}", binding.trigger);
        }
    }
    Ok(bindings)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn held_key_mapping_and_empty_defaults() {
        let b = parse("[[binding]]\ntrigger='KEY_1'\nkey='KEY_LEFTCTRL'").unwrap();
        assert_eq!(b[&KeyCode::KEY_1].remap, Some(KeyCode::KEY_LEFTCTRL));
        assert!(parse("binding=[]").unwrap().is_empty());
        assert!(parse("[[binding]]\ntrigger='KEY_1'\nkey='KEY_A'\nsteps=[{tap='KEY_B'}]").is_err());
    }

    #[test]
    fn chord_releases_in_reverse_then_waits() {
        let b = parse("[[binding]]\ntrigger='BTN_SIDE'\nsteps=[{chord=['KEY_LEFTCTRL','KEY_C']},{wait_ms=100},{tap='KEY_V'}]").unwrap();
        let m = &b[&KeyCode::BTN_SIDE];
        assert_eq!(
            m.actions
                .iter()
                .map(|a| (a.at_ms, a.key, a.pressed))
                .collect::<Vec<_>>(),
            vec![
                (0, KeyCode::KEY_LEFTCTRL, true),
                (0, KeyCode::KEY_C, true),
                (20, KeyCode::KEY_C, false),
                (20, KeyCode::KEY_LEFTCTRL, false),
                (120, KeyCode::KEY_V, true),
                (140, KeyCode::KEY_V, false),
            ]
        );
        assert_eq!(m.duration_ms, 140);
    }

    #[test]
    fn rejects_bad_macros_before_grabbing_input() {
        for steps in [
            "[{down='KEY_LEFTCTRL'}]",
            "[{up='KEY_A'}]",
            "[{chord=[]}]",
            "[{tap='KEY_A',wait_ms=1}]",
            "[{wait_ms=60001}]",
            "[{wait_ms=1}]",
            "[{tap='KEY_NOPE'}]",
            "[{chord=['KEY_A','KEY_A']}]",
            "[{down='KEY_A'},{tap='KEY_A'},{up='KEY_A'}]",
        ] {
            assert!(
                parse(&format!("[[binding]]\ntrigger='KEY_1'\nsteps={steps}")).is_err(),
                "{steps}"
            );
        }
        assert!(parse("[[binding]]\ntrigger='KEY_1'\nsteps=[{tap='KEY_A'}]\n[[binding]]\ntrigger='KEY_1'\nsteps=[{tap='KEY_B'}]").is_err());
    }
}
