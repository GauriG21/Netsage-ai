"""
ai_diagnosis.py
===============
Purpose:
  The **AI Diagnosis Module**.
  In Version 1, this is a MOCK / STUB implementation that does NOT call any
  real AI API. It simulates an AI by generating plausible diagnoses based on
  simple keyword matching.

Why a mock first:
  - Lets you build and test the FULL PIPELINE without needing API keys or internet.
  - The module has the same "interface" (input/output format) as a real AI would.
  - Later (v2), you only need to replace the inside of `call_ai()` with a real
    API call (OpenAI, Claude, etc.) — the rest of the project stays identical.

Output format:
  Same as rule_checker: list of standardized "finding" dictionaries.
  This allows comparator.py to easily compare both outputs.
"""

import os
from utils import finding, print_info, print_warning


# ============================================================
# Prompt Template Loader
# ============================================================

def load_prompt_template(prompt_file_path):
    """
    Load the AI prompt template from a markdown file.
    In v1 this is just to show the prompt concept - we don't actually send it anywhere.

    Args:
        prompt_file_path (str): Path to diagnose_prompt.md

    Returns:
        str: The prompt template text, or a default if file missing.
    """
    default_prompt = """
    You are an expert network engineer AI assistant.
    Given network symptoms, topology info, and Cisco 'show' command output,
    diagnose the issue and suggest a fix.
    """

    if not os.path.exists(prompt_file_path):
        print_warning(f"Prompt file not found: {prompt_file_path} - using default prompt")
        return default_prompt

    try:
        with open(prompt_file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print_warning(f"Could not read prompt file: {e} - using default prompt")
        return default_prompt


# ============================================================
# Mock AI Logic (Evidence-based diagnosis)
# ============================================================

def _extract_ipv4_addresses(text):
    """
    Parse all IPv4 addresses (x.x.x.x) out of a text block.
    Uses a simple regex that accepts 0-255 in each octet.
    Returns list[str] of IPs found (in order, with duplicates).
    """
    import re
    raw_ips = re.findall(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b", text)
    ips = []
    for a, b, c, d in raw_ips:
        if all(0 <= int(p) <= 255 for p in (a, b, c, d)):
            ip = f"{a}.{b}.{c}.{d}"
            # Skip obviously non-host lines like 0.0.0.0 / 255.255.255.0 appearing alone
            # (but still keep them in contexts)
            ips.append(ip)
    return ips


def _get_text(case_data):
    """Combine symptom + topology + evidence text for analysis. Uses both new and
    backwards-compat column name aliases."""
    def pick(*keys):
        for k in keys:
            val = case_data.get(k, "") or ""
            if isinstance(val, str) and val.strip():
                return val
        return ""
    s = pick("symptom", "symptoms")
    t = pick("topology")
    e = pick("show_command_evidence", "show_commands")
    return (s + "\n" + t + "\n" + e).lower()


def _add_fields(f, root_cause, confidence, osi_layer, next_command, fix_steps):
    """Attach extra structured fields to a finding dict. The base finding()
    dict keeps issue/severity/evidence/suggestion so existing comparator/human_review
    modules still work. Extra fields are used in v2-style reports."""
    f["root_cause"] = root_cause
    f["confidence"] = confidence
    f["osi_layer"] = osi_layer
    f["next_command"] = next_command
    f["fix_steps"] = fix_steps
    return f


def _mock_ai_keyword_analysis(case_data):
    """
    INTERNAL helper. Evidence-based mock diagnosis.

    Strategy:
      1. Pre-process the case text to extract structured facts (IPs, masks,
         VLANs, interface status lines, static routes).
      2. Run diagnostic checks in DESCENDING priority:
           high-confidence explicit findings (duplicate IPs, interface down)
         > medium-confidence structural findings (wrong mask, missing VLAN,
           missing static route, wrong gateway)
         > low-confidence generic fallback findings.
      3. Stop adding low-confidence generic findings if we already have at
         least one high-confidence explicit finding, to avoid false positives
         like "potential subnet mask issue" just because 'mask' was mentioned.

    Returns list of finding dicts in the standard format (+ extra fields).
    """
    import re

    text = _get_text(case_data)
    case_sensitive_text = (
        (case_data.get("symptom") or case_data.get("symptoms") or "")
        + "\n"
        + (case_data.get("topology") or "")
        + "\n"
        + (case_data.get("show_command_evidence") or case_data.get("show_commands") or "")
    )
    findings = []
    explicit_high_confidence = False

    # ------------------------------------------------------------
    # PRIORITY 1: DUPLICATE IP ADDRESS (explicit evidence detection)
    # ------------------------------------------------------------
    # Look for ALL occurrences of IPv4 Address blocks in ipconfig output.
    # Example:
    #   PC0> ipconfig
    #   IPv4 Address: 192.168.1.10
    #   ...
    #   PC1> ipconfig
    #   IPv4 Address: 192.168.1.10
    # We count IPs that appear in multiple IPv4 Address: lines, or anywhere
    # 2+ times in the full text AND the text also contains the word
    # 'duplicate'/'conflict'/'two different devices'/'same ip'.
    ip_lines = []  # list of (device_label, ip)
    device_label = "unknown"
    for raw_line in case_sensitive_text.splitlines():
        line = raw_line.rstrip()
        # Detect device prompt like PC0>, PC1>, S1#, R1(config-if)#
        m = re.search(r"([A-Za-z][A-Za-z0-9_-]{0,15})\s*[>#]", line)
        if m:
            device_label = m.group(1).strip()
        # Detect IPv4 Address line (tolerate many formatting styles)
        m2 = re.search(
            r"IPv4\s*Address[ .:]*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
            line,
            re.IGNORECASE,
        )
        if m2:
            ip_lines.append((device_label, m2.group(1)))
        # Also catch 'IP Address. . . . : x.x.x.x' style
        m3 = re.search(
            r"(?:^|\s)IP\s*Address[ .:]*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
            line,
            re.IGNORECASE,
        )
        if m3 and not m2:  # avoid double count if IPv4 line already matched
            ip_lines.append((device_label, m3.group(1)))

    # Count occurrences per IP, listing distinct devices it appears on
    ip_to_devices = {}
    for dev, ip in ip_lines:
        ip_to_devices.setdefault(ip, set()).add(dev)

    duplicates = {
        ip: sorted(devs)
        for ip, devs in ip_to_devices.items()
        if len(devs) >= 2
    }

    # Heuristic backup: text explicitly says same IP on two devices
    explicit_duplicate_phrases = (
        ("duplicate" in text and "ip" in text)
        or ("conflict" in text and "ip" in text)
        # Match "same IP address" or "same IPv4 address" but NOT "same IP network" or "same IP subnet"
        or ("same ip address" in text)
        or ("same ipv4 address" in text)
        or re.search(r"\bsame\s+ip\s*(?!\s*(network|subnet|broadcast))\b", text) is not None
        or ("two different devices" in text)
        or ("%ip-4-dupaddr" in text)  # Cisco syslog ID
    )
    # Count IPs that appear 2+ times anywhere in the evidence text
    all_ips = _extract_ipv4_addresses(text)
    from collections import Counter
    ip_counts = Counter(all_ips)
    # Exclude common non-host IPs from "duplicate" detection by frequency alone
    # (e.g. subnet mask 255.255.255.0, default 0.0.0.0, gateways appearing legitimately twice,
    #  network addresses ending in .0, broadcast addresses ending in .255)
    frequency_dupes = [
        ip
        for ip, count in ip_counts.items()
        if count >= 2
        and ip not in ("0.0.0.0", "255.255.255.0", "255.255.0.0", "255.0.0.0")
        and not (ip.endswith(".1"))  # .1 is gateway and often repeated legitimately
        and not (ip.endswith(".0"))  # .0 is network address, not a host
        and not (ip.endswith(".255"))  # .255 is broadcast, not a host
    ]

    duplicate_ips = sorted(set(list(duplicates.keys()) + [
        ip for ip in frequency_dupes if explicit_duplicate_phrases
    ]))

    if duplicate_ips:
        dup_ip = duplicate_ips[0]
        dup_devs = duplicates.get(dup_ip, [])
        if dup_devs:
            devices_str = " and ".join(dup_devs)
        else:
            devices_str = "multiple hosts"
        evidence_str = (
            f"{devices_str} are both configured with {dup_ip}"
        )
        f = finding(
            issue=f"Duplicate IP Address - {dup_ip} assigned to multiple devices",
            severity="high",
            evidence=f"AI extracted IPv4 addresses from ipconfig output. {evidence_str}. "
                     f"Keyword context also shows conflict/duplicate language: "
                     f"'duplicate IP'/'same IPv4 address'/'two different devices' detected.",
            suggestion=(
                "Assign a unique, unused IP address to one of the devices, "
                "then verify connectivity with ping."
            ),
        )
        _add_fields(
            f,
            root_cause="Duplicate IP Address",
            confidence="High",
            osi_layer="Layer 3",
            next_command="Check IP configuration on all connected hosts",
            fix_steps=(
                "Assign a unique unused IP address to one of the devices, "
                "then test connectivity again."
            ),
        )
        findings.append(f)
        explicit_high_confidence = True

    # ------------------------------------------------------------
    # PRIORITY 2: Interface administratively down
    # ------------------------------------------------------------
    down_hits = []
    if "administratively down" in text:
        down_hits.append("'administratively down' appears in show output")
    if re.search(r"\bis\s+administratively\s+down\b", text):
        down_hits.append("interface status line reports administratively down")
    if ("shutdown" in text) and (
        ("interface" in text) or re.search(r"^\s*shutdown\s*$", case_sensitive_text, re.MULTILINE)
    ):
        down_hits.append("running-config contains 'shutdown' under an interface")
    if len(down_hits) >= 1 and ("interface" in text or "fastethernet" in text or "gigabitethernet" in text or "serial" in text):
        f = finding(
            issue="Interface is administratively down (shutdown)",
            severity="high",
            evidence="AI found interface-down markers: " + "; ".join(down_hits),
            suggestion=(
                "Enable the affected interface in global config mode:\n"
                "  interface <name>\n"
                "  no shutdown\n"
                "Then verify with 'show ip interface brief'."
            ),
        )
        _add_fields(
            f,
            root_cause="Interface Administratively Down",
            confidence="High",
            osi_layer="Layer 2",
            next_command="show ip interface brief",
            fix_steps=(
                "Enter interface configuration mode for the disabled port and "
                "run 'no shutdown', then verify the interface status changes to up/up."
            ),
        )
        findings.append(f)
        explicit_high_confidence = True

    # ------------------------------------------------------------
    # PRIORITY 3: VLAN problems - two flavours:
    #               (a) MISSING VLAN     (VLAN inactive / referenced, not created)
    #               (b) ASSIGNMENT MISMATCH (ports in same IP subnet but
    #                   assigned to DIFFERENT existing VLANs -> L2 isolation)
    # ------------------------------------------------------------
    # Parse "Access Mode VLAN: NN" from each "show interfaces <X> switchport"
    # block in the case-sensitive raw text. This works for both flavours:
    #   - For (a) we'll see "Access Mode VLAN: NN (Inactive)"
    #   - For (b) we'll see two ports with two DIFFERENT active NN values.
    import re as _re
    port_to_vlan = {}
    current_port = None
    for raw_line in case_sensitive_text.splitlines():
        line = raw_line.rstrip()
        m_cmd = _re.search(
            r"show\s+interfaces\s+([A-Za-z0-9 /]+?)\s+switchport",
            line, _re.IGNORECASE,
        )
        if m_cmd:
            port = m_cmd.group(1).strip()
            # Remove spaces between interface type and number (e.g., "FastEthernet 0/11" -> "FastEthernet0/11")
            port = _re.sub(r"([A-Za-z])\s+(\d)", r"\1\2", port)
            norm = _re.sub(r"^FastEthernet", "Fa", port, flags=_re.IGNORECASE)
            norm = _re.sub(r"^GigabitEthernet", "Gi", norm, flags=_re.IGNORECASE)
            current_port = norm
            continue
        if current_port is None:
            continue
        m_vlan = _re.search(
            r"Access\s*Mode\s*VLAN\s*:\s*(\d{1,4})\s*(?:\(([^)]*)\))?",
            line, _re.IGNORECASE,
        )
        if m_vlan:
            vid = int(m_vlan.group(1))
            status = (m_vlan.group(2) or "").strip()
            port_to_vlan[current_port] = (vid, status)
            current_port = None

    # Flavour (a) MISSING VLAN detection
    vlan_hits_missing = []
    if any(st.lower() == "inactive" for _, st in port_to_vlan.values()):
        vlan_hits_missing.append("'Access Mode VLAN: NN (Inactive)' flag present")
    # Does topology mention VLAN IDs that don't appear in show vlan output?
    vlan_ids_expected = set(int(x) for x in re.findall(r"\bvlan\s*(\d{1,4})", text, re.IGNORECASE))
    # Look for 'show vlan brief' style table (numbers at start of line)
    vlan_ids_present = set()
    for line in re.findall(r"^\s*(\d{1,4})\s+[a-z]", text, re.MULTILINE):
        vlan_ids_present.add(int(line))
    missing_vlans = sorted(vid for vid in vlan_ids_expected if vlan_ids_present and vid not in vlan_ids_present and vid > 1 and vid < 1002)
    if missing_vlans:
        vlan_hits_missing.append(f"VLAN IDs {missing_vlans} referenced but absent from vlan table")
    if "vlan" in text and ("missing" in text or "does not exist" in text):
        vlan_hits_missing.append("explicit text says VLAN is missing / does not exist")

    # Flavour (b) ASSIGNMENT MISMATCH detection
    vlan_hits_mismatch = []
    assigned_vids = {vid for vid, _ in port_to_vlan.values()}
    if len(assigned_vids) >= 2:
        # More than one access VLAN configured. Now check if the end hosts are
        # in the same IP subnet (same first-3-octets prefix appearing 2+ times
        # for host IPs, or an explicit "same IP subnet"/"same IP network" note).
        same_subnet_hint = False
        if "same ip subnet" in text or "same ip network" in text or "same broadcast domain" in text:
            same_subnet_hint = True
        else:
            from collections import Counter as _CCounter
            prefixes = _CCounter()
            for m_ip in re.finditer(
                r"\b(\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d{1,3})\b", case_sensitive_text
            ):
                first_three = m_ip.group(1)
                last_octet = int(m_ip.group(2))
                if first_three in ("0.0.0", "255.255.255", "255.255.0", "255.0.0"):
                    continue
                if 1 < last_octet < 254:
                    prefixes[first_three] += 1
            if any(cnt >= 2 for cnt in prefixes.values()):
                same_subnet_hint = True
        if same_subnet_hint:
            # Make sure both VLANs actually EXIST (inactive ones would be the
            # missing-VLAN flavour instead).
            all_active = all(st.lower() != "inactive" for _, st in port_to_vlan.values())
            if all_active:
                mapping = ", ".join(
                    f"{p} -> VLAN{v} ({s or 'active'})" for p, (v, s) in sorted(port_to_vlan.items())
                )
                vlan_hits_mismatch.append(
                    f"Access ports assigned DIFFERENT VLANs {sorted(assigned_vids)} while hosts share an IP subnet: {mapping}"
                )
    if (
        "vlan" in text
        and ("different vlan" in text or "vlan assignment" in text or "wrong vlan" in text)
        and "same ip subnet" in text
    ):
        vlan_hits_mismatch.append(
            "explicit note references same subnet but different VLAN assignments"
        )

    # Emit findings. MISMATCH (b) has priority over MISSING (a) when both apply,
    # because if ports are split across different VLANs AND one VLAN is missing,
    # the assignment problem is the more-specific correct diagnosis.
    if len(vlan_hits_mismatch) >= 1:
        f = finding(
            issue="VLAN Assignment Mismatch - same IP subnet but different access VLANs",
            severity="high",
            evidence="AI detected VLAN assignment-mismatch indicators: " + "; ".join(vlan_hits_mismatch),
            suggestion=(
                "Assign all access ports that serve the same IP subnet to the "
                "SAME VLAN on the switch. For each port:\n"
                "  enable\n"
                "  configure terminal\n"
                "  interface <port>\n"
                "   switchport mode access\n"
                "   switchport access vlan <correct_id>\n"
                "  end\n"
                "Verify with 'show vlan brief' and ping between the end hosts."
            ),
        )
        _add_fields(
            f,
            root_cause="VLAN Assignment Mismatch",
            confidence="High",
            osi_layer="Layer 2",
            next_command="show vlan brief ; show interfaces <port> switchport for each affected port",
            fix_steps=(
                "Reassign the mismatched access ports so they all belong to the "
                "same VLAN on the switch, then re-run ping between the end hosts "
                "to confirm Layer 2 connectivity is restored."
            ),
        )
        findings.append(f)
        explicit_high_confidence = True
    elif len(vlan_hits_missing) >= 1:
        f = finding(
            issue="Missing VLAN - referenced VLAN was never created on the switch",
            severity="high",
            evidence="AI detected missing-VLAN indicators: " + "; ".join(vlan_hits_missing),
            suggestion=(
                "Create the VLAN on the switch:\n"
                "  enable\n"
                "  configure terminal\n"
                "  vlan <vlan_id>\n"
                "   name <DescriptiveName>\n"
                "  end\n"
                "Verify with 'show interfaces <port> switchport' that Access Mode VLAN becomes 'active'."
            ),
        )
        _add_fields(
            f,
            root_cause="Missing VLAN",
            confidence="High",
            osi_layer="Layer 2",
            next_command="show interfaces <port> switchport ; show vlan brief",
            fix_steps=(
                "Create the required VLAN on the switch using the 'vlan <id>' command, "
                "then reassign the port to the now-existing VLAN with "
                "'switchport access vlan <id>'."
            ),
        )
        findings.append(f)
        explicit_high_confidence = True

    # ------------------------------------------------------------
    # PRIORITY 4: Wrong subnet mask (requires EVIDENCE, not just the word)
    # ------------------------------------------------------------
    mask_hits = []
    # Style 1: explicit (WRONG ...) annotation beside Subnet Mask line
    if re.search(r"mask.*\(wrong", text, re.IGNORECASE) or re.search(r"\(wrong[^\n]*mask", text, re.IGNORECASE):
        mask_hits.append("explicit (WRONG) annotation on a subnet mask line")
    # Style 2: multiple different subnet masks listed for devices on the same LAN
    #         (e.g. PC0 /24, PC1 /16)
    found_masks = set()
    for m in re.finditer(
        r"subnet[ -]mask[ .:]*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
        text, re.IGNORECASE,
    ):
        found_masks.add(m.group(1))
    # Topology expected mask
    expected_masks = set(re.findall(r"255\.\d{1,3}\.\d{1,3}\.\d{1,3}", case_data.get("topology", "")))
    if len(found_masks) > 1:
        mask_hits.append(
            f"multiple different subnet masks configured across devices: {sorted(found_masks)}"
        )
    if expected_masks and found_masks:
        for actual in found_masks:
            if actual not in expected_masks:
                mask_hits.append(
                    f"configured mask {actual} not in topology plan mask(s) {sorted(expected_masks)}"
                )
                break
    if ("/24" in case_data.get("topology", "").lower() or "255.255.255.0" in case_data.get("topology", "")) and "255.255.0.0" in text:
        mask_hits.append("topology expects /24 but a device configured /16 (255.255.0.0)")
    if mask_hits:
        f = finding(
            issue="Incorrect or mismatched subnet mask",
            severity="high",
            evidence="AI found mismatched-mask evidence: " + "; ".join(mask_hits),
            suggestion=(
                "Apply the correct planned subnet mask uniformly across all devices on "
                "that LAN segment. For /24 networks use 255.255.255.0."
            ),
        )
        _add_fields(
            f,
            root_cause="Wrong Subnet Mask",
            confidence="High",
            osi_layer="Layer 3",
            next_command="Run ipconfig /all on every end device and compare Subnet Mask values",
            fix_steps=(
                "Reconfigure the mismatched device(s) with the correct planned subnet "
                "mask for that LAN segment, then ping between hosts to confirm connectivity."
            ),
        )
        findings.append(f)
        explicit_high_confidence = True

    # ------------------------------------------------------------
    # PRIORITY 5: Default gateway mismatch (configured gateway != topology gateway)
    # ------------------------------------------------------------
    gw_hits = []
    # Parse configured gateways from ipconfig output (non-0.0.0.0 values)
    configured_gws = []
    for m in re.finditer(
        r"default[- ]gateway[ .:]*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
        text, re.IGNORECASE,
    ):
        configured_gws.append(m.group(1))
    # Candidate topology gateways: IPs ending in .1 mentioned alongside "router" or "gateway"
    topology_text = (case_data.get("topology") or "").lower()
    topology_gws = []
    for ip in re.findall(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", topology_text):
        if ip.endswith(".1") or "router" in topology_text or "gateway" in topology_text:
            topology_gws.append(ip)
    if configured_gws and topology_gws:
        non_zero_gws = [g for g in configured_gws if g != "0.0.0.0"]
        if "0.0.0.0" in configured_gws:
            gw_hits.append("default gateway set to 0.0.0.0 (not configured)")
        for gw in non_zero_gws:
            if gw not in topology_gws:
                gw_hits.append(
                    f"configured gateway {gw} does not match any topology-declared router/gateway IP in {sorted(set(topology_gws))}"
                )
    if ("cannot reach" in text or "cannot ping" in text) and (
        "different subnet" in text or "remote subnet" in text or "other subnet" in text
    ):
        gw_hits.append("symptom: cannot reach devices on a different subnet")
    if re.search(r"gateway[^\n]*\(wrong", text, re.IGNORECASE):
        gw_hits.append("explicit (WRONG) annotation on a default gateway line")
    if gw_hits:
        f = finding(
            issue="Default gateway is missing or incorrect",
            severity="medium",
            evidence="AI found gateway-mismatch indicators: " + "; ".join(gw_hits),
            suggestion=(
                "On the end device set Default Gateway to the correct router LAN IP "
                "(usually x.x.x.1 for that subnet)."
            ),
        )
        _add_fields(
            f,
            root_cause="Default Gateway Mismatch",
            confidence="High",
            osi_layer="Layer 3",
            next_command="Verify router LAN IP and compare to end-device configured Default Gateway",
            fix_steps=(
                "Reconfigure the end device Default Gateway value to match the "
                "actual router interface IP for that LAN; confirm cross-subnet ping works."
            ),
        )
        findings.append(f)
        explicit_high_confidence = True

    # ------------------------------------------------------------
    # PRIORITY 6: Missing static route (two routers, no S entries)
    # ------------------------------------------------------------
    sr_hits = []
    two_routers = (
        ("r1" in topology_text and "r2" in topology_text)
        or ("router1" in topology_text and "router2" in topology_text)
        or ("two router" in topology_text) or ("2 router" in topology_text)
    )
    if two_routers:
        sr_hits.append("topology declares two routers")
    if "show ip route" in text:
        # Only looks for the static route letter 'S ' in the codes table output
        if re.search(r"^[^a-z]*s[ -]", text, re.MULTILINE) is None:
            # No static routes seen in any line
            # But "Codes:" lines mention S - code letter so ignore that
            # Safer heuristic: no "ip route" configuration commands found, and
            # only connected C lines visible
            if re.search(r"^c\s+\d{1,3}\.", text, re.MULTILINE) is not None:
                # At least one C (connected) line exists
                if "static route" in text and (
                    "missing" in text or "absent" in text or "no 's'" in text or "no s entry" in text
                ):
                    sr_hits.append("show ip route has no S (static) entry; explicit missing/absent note found")
                elif ("192.168.1.0" in text and "192.168.2.0" not in text) or (
                    "192.168.2.0" in text and "192.168.1.0" not in text
                ):
                    sr_hits.append("routing table shows only one LAN subnet - opposite LAN subnet missing")
    if len(sr_hits) >= 2:
        f = finding(
            issue="Missing static route(s) between two routers",
            severity="high",
            evidence="AI detected two-router topology missing static route evidence: "
                     + "; ".join(sr_hits),
            suggestion=(
                "Add bidirectional static routes. On R1: ip route <R2_LAN> <mask> <next_hop_R2_IP>. "
                "On R2: ip route <R1_LAN> <mask> <next_hop_R1_IP>."
            ),
        )
        _add_fields(
            f,
            root_cause="Missing Static Route",
            confidence="High",
            osi_layer="Layer 3",
            next_command="show ip route on R1 and R2",
            fix_steps=(
                "Configure a static route on R1 toward R2's LAN and a matching static "
                "route on R2 toward R1's LAN, then verify ping succeeds between the two LANs."
            ),
        )
        findings.append(f)
        explicit_high_confidence = True

    # ------------------------------------------------------------
    # PRIORITY 7: Cable / physical (Layer 1) issues
    # ------------------------------------------------------------
    phys_hits = []
    if "link light" in text and ("off" in text or "out" in text):
        phys_hits.append("link light reported off/out")
    if "cable" in text:
        phys_hits.append("cable referenced in case description")
    if "no link" in text:
        phys_hits.append("'no link' symptom reported")
    if ("down/down" in text or "notconnect" in text) and "administratively" not in text:
        phys_hits.append("interface down/down (not admin down) indicates cable/port issue")
    if len(phys_hits) >= 1 and not explicit_high_confidence:
        f = finding(
            issue="Possible Layer 1 / physical connection issue",
            severity="medium",
            evidence="AI detected physical-layer indicators: " + "; ".join(phys_hits),
            suggestion=(
                "Reseat or replace the Ethernet cable on both ends, try a different "
                "switch port, verify the correct cable type, and confirm link lights come on."
            ),
        )
        _add_fields(
            f,
            root_cause="Suspected Physical Cable / Port Fault",
            confidence="Medium",
            osi_layer="Layer 1",
            next_command="Inspect link lights, then run show interfaces status",
            fix_steps=(
                "Replace the Ethernet cable, move the connection to a known-good switch "
                "port, and re-test until the link indicator lights on both ends."
            ),
        )
        findings.append(f)

    # ------------------------------------------------------------
    # PRIORITY 8 (LOW): Generic connectivity / DNS fallback findings
    #                  Only added if we found NO explicit high-confidence fault.
    # ------------------------------------------------------------
    if not explicit_high_confidence:
        if "vlan" in text and not any("vlan" in f["root_cause"].lower() for f in findings):
            f = finding(
                issue="Possible VLAN configuration problem",
                severity="medium",
                evidence="AI noted VLAN keywords in the case but could not confirm a specific fault",
                suggestion=(
                    "Verify that VLANs exist and that access/trunk ports are assigned "
                    "correctly."
                ),
            )
            _add_fields(
                f,
                root_cause="Potential VLAN Issue",
                confidence="Low",
                osi_layer="Layer 2",
                next_command="show vlan brief ; show interfaces trunk",
                fix_steps=(
                    "Double-check VLAN creation, switchport mode, and allowed VLANs on "
                    "trunks; reassign ports to the correct VLAN where needed."
                ),
            )
            findings.append(f)

        if "dns" in text or "cannot resolve" in text:
            f = finding(
                issue="Possible DNS or name resolution issue",
                severity="low",
                evidence="AI detected DNS/name-resolution related keywords",
                suggestion=(
                    "Confirm DNS server IP on the client; test connectivity by IP to "
                    "isolate DNS from routing."
                ),
            )
            _add_fields(
                f,
                root_cause="Potential DNS Issue",
                confidence="Low",
                osi_layer="Layer 7",
                next_command="nslookup <hostname> and direct ping by IP",
                fix_steps=(
                    "Set a valid DNS server address on the end device and confirm the "
                    "DNS server itself is reachable via ping."
                ),
            )
            findings.append(f)

        connectivity_symptom = (
            "cannot ping" in text or "no connectivity" in text or "unreachable" in text
        )
        if connectivity_symptom and not findings:
            f = finding(
                issue="Generic IP connectivity failure between devices",
                severity="high",
                evidence="AI sees ping/connectivity-failure symptoms with no more-specific root cause",
                suggestion=(
                    "Troubleshoot step-by-step: (1) verify end-device IPs and masks, "
                    "(2) verify gateways, (3) ping default gateway, (4) run traceroute "
                    "to the failing destination to isolate the hop."
                ),
            )
            _add_fields(
                f,
                root_cause="Undiagnosed Connectivity Fault",
                confidence="Low",
                osi_layer="Layer 3",
                next_command="ping default-gateway, then tracert <dest>",
                fix_steps=(
                    "Walk the path one hop at a time (end device -> gateway -> remote "
                    "gateway -> remote device) until the failing hop is identified."
                ),
            )
            findings.append(f)

    # ------------------------------------------------------------
    # Final generic fallback
    # ------------------------------------------------------------
    if not findings:
        f = finding(
            issue="AI could not confidently identify a specific root cause",
            severity="low",
            evidence="Case data lacked explicit evidence matching any known fault pattern",
            suggestion=(
                "Gather more evidence: 'show running-config', 'show log', a precise "
                "list of which devices can/cannot ping each other, and the exact "
                "error output from failing pings/traceroutes."
            ),
        )
        _add_fields(
            f,
            root_cause="Insufficient Evidence",
            confidence="Low",
            osi_layer="Unknown",
            next_command="Collect show running-config and full ping/tracert output",
            fix_steps=(
                "Collect additional diagnostic output and re-run the diagnosis once "
                "more evidence is available."
            ),
        )
        findings.append(f)

    # Tag AI source
    for f in findings:
        f["source"] = "ai_diagnosis"
        f["model"] = "mock_evidence_v2"

    return findings


# ============================================================
# Main AI Entry Point
# ============================================================

def call_ai(case_data, prompt_file_path=None, use_real_api=False):
    """
    Main public function: get AI diagnosis for a case.

    Args:
        case_data (dict): The case (symptoms, topology, show_commands, ...).
        prompt_file_path (str|None): Optional path to the prompt template file.
        use_real_api (bool): FOR V2. If True, call real AI API. In v1 must be False.

    Returns:
        list[dict]: AI findings in the SAME format as rule_checker output.
    """
    case_id = case_data.get("case_id", "unknown")
    print_info("Running AI Diagnosis Module...")

    # Step 1: Load prompt template (just to demonstrate the concept)
    if prompt_file_path:
        prompt_template = load_prompt_template(prompt_file_path)
        # In v2: you'd insert case data into the prompt template here
        print_info(f"  Loaded prompt template ({len(prompt_template)} chars)")

    # Step 2: Run diagnosis
    if use_real_api:
        # ----------------------------------------------------------
        # V2 PLACEHOLDER - Real AI API integration goes here.
        # Example sketch (pseudo-code):
        #   filled_prompt = prompt_template.format(**case_data)
        #   response = openai.chat.completions.create(model="gpt-4o",
        #                                             messages=[{"role":"user","content":filled_prompt}])
        #   findings = _parse_ai_response_into_findings(response.text)
        # ----------------------------------------------------------
        raise NotImplementedError(
            "Real AI API is NOT implemented in Version 1. "
            "Set use_real_api=False to use the mock AI."
        )
    else:
        print_info("  (Using MOCK AI diagnosis - no real API call made)")
        findings = _mock_ai_keyword_analysis(case_data)

    print_info(f"AI diagnosis completed: {len(findings)} finding(s) for case {case_id}")
    return findings
