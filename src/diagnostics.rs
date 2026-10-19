//! Passive sysfs inventory. Never open input/hidraw devices or request feature reports.
use crate::devices;
use serde_json::{Value, json};
use std::{fs, path::Path};

fn read(path: &Path) -> String {
    fs::read_to_string(path)
        .unwrap_or_default()
        .trim()
        .to_owned()
}

fn hex(path: &Path) -> Option<u16> {
    u16::from_str_radix(&read(path), 16).ok()
}

fn identity(bus: u16, vendor: u16, product: u16) -> Value {
    json!({"bus":format!("{bus:04x}"), "vendor":format!("{vendor:04x}"), "product":format!("{product:04x}"),
        "model": if bus == 3 { devices::lookup(vendor, product) } else { None }})
}

pub fn collect(root: &Path) -> Value {
    let mut warnings = Vec::new();
    let mut inputs = Vec::new();
    match fs::read_dir(root.join("sys/class/input")) {
        Ok(entries) => {
            for entry in entries.flatten() {
                let node = entry.file_name().to_string_lossy().into_owned();
                if !node.starts_with("event") {
                    continue;
                }
                let base = entry.path().join("device");
                if hex(&base.join("id/vendor")) != Some(0x1532) {
                    continue;
                }
                let mut info = identity(
                    hex(&base.join("id/bustype")).unwrap_or(0),
                    0x1532,
                    hex(&base.join("id/product")).unwrap_or(0),
                );
                info["path"] = json!(format!("/dev/input/{node}"));
                info["name"] = json!(read(&base.join("name")));
                info["capabilities"] = json!({"key":read(&base.join("capabilities/key")), "rel":read(&base.join("capabilities/rel")), "abs":read(&base.join("capabilities/abs"))});
                inputs.push(info);
            }
        }
        Err(e) => warnings.push(format!("Cannot enumerate input interfaces: {e}")),
    }
    let mut hid = Vec::new();
    match fs::read_dir(root.join("sys/class/hidraw")) {
        Ok(entries) => {
            for entry in entries.flatten() {
                let node = entry.file_name().to_string_lossy().into_owned();
                if !node.starts_with("hidraw") {
                    continue;
                }
                let base = entry.path().join("device");
                let properties = read(&base.join("uevent"));
                let Some(id) = properties.lines().find_map(|l| l.strip_prefix("HID_ID=")) else {
                    continue;
                };
                let parts: Vec<_> = id.split(':').collect();
                if parts.len() != 3 || u32::from_str_radix(parts[1], 16).ok() != Some(0x1532) {
                    continue;
                }
                let mut info = identity(
                    u16::from_str_radix(parts[0], 16).unwrap_or(0),
                    0x1532,
                    u32::from_str_radix(parts[2], 16).unwrap_or(0) as u16,
                );
                info["path"] = json!(format!("/dev/{node}"));
                info["name"] = json!(
                    properties
                        .lines()
                        .find_map(|l| l.strip_prefix("HID_NAME="))
                        .unwrap_or_default()
                );
                // Deliberate allowlist: HID_UNIQ, HID_PHYS, serial and raw uevent
                // must not enter a report intended for public support requests.
                match fs::read(base.join("report_descriptor")) {
                    Ok(bytes) => {
                        info["report_descriptor_length"] = json!(bytes.len());
                        info["report_descriptor_hex"] = json!(
                            bytes
                                .iter()
                                .take(16384)
                                .map(|b| format!("{b:02x}"))
                                .collect::<String>()
                        );
                        if bytes.len() > 16384 {
                            info["descriptor_truncated"] = json!(true);
                        }
                    }
                    Err(e) => info["descriptor_error"] = json!(e.to_string()),
                }
                hid.push(info);
            }
        }
        Err(e) => warnings.push(format!("Cannot enumerate HID interfaces: {e}")),
    }
    inputs.sort_by_key(|v| v["path"].as_str().unwrap_or_default().to_owned());
    hid.sort_by_key(|v| v["path"].as_str().unwrap_or_default().to_owned());
    let release = read(&root.join("etc/os-release"));
    let field = |name: &str| {
        release
            .lines()
            .find_map(|line| line.strip_prefix(&format!("{name}=")))
            .unwrap_or_default()
            .trim_matches('"')
            .to_owned()
    };
    json!({"report_version":1, "engine_version":env!("CARGO_PKG_VERSION"), "collection":"passive_sysfs_only",
        "os":{"id":field("ID"), "version_id":field("VERSION_ID"), "kernel":read(&root.join("proc/sys/kernel/osrelease"))},
        "inputs":inputs, "hidraw":hid, "warnings":warnings})
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unknown_devices_are_reported_without_serials_or_other_devices() {
        let root =
            std::env::temp_dir().join(format!("nagalibre-diagnostics-{}", std::process::id()));
        let input = root.join("sys/class/input/event9/device");
        let hid = root.join("sys/class/hidraw/hidraw7/device");
        fs::create_dir_all(input.join("id")).unwrap();
        fs::create_dir_all(&hid).unwrap();
        fs::write(input.join("id/vendor"), "1532").unwrap();
        fs::write(input.join("id/product"), "ffff").unwrap();
        fs::write(input.join("id/bustype"), "0003").unwrap();
        fs::write(input.join("uniq"), "PRIVATE_SERIAL").unwrap();
        fs::write(hid.join("uevent"),"HID_ID=0003:00001532:0000FFFF\nHID_NAME=Razer test mouse\nHID_UNIQ=PRIVATE_SERIAL\nHID_PHYS=PRIVATE_LOCATION").unwrap();
        fs::write(hid.join("report_descriptor"), [0x05, 0x01, 0x09, 0x02]).unwrap();
        let other = root.join("sys/class/hidraw/hidraw8/device");
        fs::create_dir_all(&other).unwrap();
        fs::write(
            other.join("uevent"),
            "HID_ID=0003:00001234:00000001\nHID_NAME=PRIVATE_OTHER_DEVICE",
        )
        .unwrap();
        let report = collect(&root);
        assert_eq!(report["inputs"].as_array().unwrap().len(), 1);
        assert_eq!(report["hidraw"].as_array().unwrap().len(), 1);
        assert!(report["inputs"][0]["model"].is_null());
        assert_eq!(report["hidraw"][0]["report_descriptor_hex"], "05010902");
        assert!(!report.to_string().contains("PRIVATE_"));
        fs::remove_dir_all(root).unwrap();
    }
}
