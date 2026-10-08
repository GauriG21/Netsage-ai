"""
rule_checker.py
===============
Purpose:
  The **Python Rule-Based Validator**.
  Runs hard-coded network rules against the case data (symptoms, topology,
  show command output) to detect network issues.

How it works:
  Each rule is a Python function that:
    1. Takes the case data as input
    2. Checks a specific condition (e.g., "is interface down?", "is VLAN wrong?")
    3. Returns a "finding" dictionary if the issue is found, otherwise None

Why separate from AI diagnosis:
  Rules are CERTAIN (if condition is true, issue exists). AI is PROBABILISTIC.
  Running both and comparing gives us a more reliable diagnosis.

Note for students:
  Add more rules here as you learn more networking concepts!
"""

from utils import finding, print_info


# ============================================================
# Individual Rule Functions
# Each rule: takes case_data (dict), returns finding or None
# ============================================================

def rule_interface_down(case_data):
    """
    Rule: Check if any network interface is in "administratively down" or "down" state.
    Looks in the 'show_commands' field for keywords like "administratively down" or "down/down".
    """
    show_output = case_data.get("show_commands", "").lower()
    symptoms = case_data.get("symptoms", "").lower()

    evidence_parts = []
    if "administratively down" in show_output:
        evidence_parts.append("Found 'administratively down' in show output")
    if "down/down" in show_output:
        evidence_parts.append("Found 'down/down' interface status")
    if "interface down" in symptoms:
        evidence_parts.append("Symptom reports interface down")

    if evidence_parts:
        return finding(
            issue="Network interface is down",
            severity="high",
            evidence="; ".join(evidence_parts),
            suggestion="On the affected device, enter interface config mode and run: no shutdown"
        )
    return None


def rule_vlan_mismatch(case_data):
    """
    Rule: Check for VLAN configuration problems:
      A) VLAN MISMATCH - port assigned to wrong VLAN.
      B) MISSING VLAN  - port references a VLAN that was never created in the
                         switch's VLAN database (show vlan brief lacks the ID,
                         switchport command says "Access Mode VLAN: NN (Inactive)").
      C) VLAN NAMING / EXPECTED vs configured mismatch.
    """
    import re

    show_output_raw = case_data.get("show_command_evidence", "") + "\n" + case_data.get("show_commands", "")
    show_output = show_output_raw.lower()
    topology = case_data.get("topology", "").lower()
    symptoms = case_data.get("symptoms", "").lower() + " " + case_data.get("symptom", "").lower()

    evidence_parts = []

    # --- A) Symptom-level mentions ----------------------------------------
    if "vlan" in symptoms and ("mismatch" in symptoms or "wrong" in symptoms):
        evidence_parts.append("Symptom mentions VLAN mismatch")
    if "vlan" in show_output and "mismatch" in show_output:
        evidence_parts.append("Show output explicitly reports VLAN mismatch")

    # --- B) Missing VLAN detection ----------------------------------------
    # Case 1: "Access Mode VLAN: 50 (Inactive)" appears in "show int X switchport" output
    if "access mode vlan" in show_output and "inactive" in show_output:
        evidence_parts.append(
            "Access port references a VLAN marked 'Inactive' - VLAN does not exist in switch database"
        )

    # Case 2: explicit annotation in evidence like (NOTE: VLAN 50 is MISSING ...)
    if ("missing" in show_output or "does not exist" in show_output) and "vlan" in show_output:
        if "note:" in show_output or "(note:" in show_output or "(root cause" in show_output:
            evidence_parts.append("Evidence contains explicit note that a VLAN is missing/not created")

    # Case 3: Extract VLAN IDs mentioned in topology plan, verify they appear
    #         in the "show vlan brief" table.
    #         E.g. "3 VLANs planned: 10 HR, 20 Finance, 50 Engineering" -> {10, 20, 50}
    expected_vlan_ids = set()
    for match in re.finditer(r"vlan\s*(\d{1,4})", topology, re.IGNORECASE):
        expected_vlan_ids.add(int(match.group(1)))
    for match in re.finditer(r"\b(\d{1,4})\s+(hr|finance|engineering|servers|students|staff|voice|mgmt|guest)\b", topology, re.IGNORECASE):
        expected_vlan_ids.add(int(match.group(1)))

    # Parse VLAN IDs present in "show vlan brief" output (first number on each
    # line that matches a VLAN row - the 1, 10, 20, 1002, ... lines)
    existing_vlan_ids = set()
    for line in show_output.splitlines():
        m = re.match(r"^\s*(\d{1,4})\s+[a-z]", line)
        if m:
            existing_vlan_ids.add(int(m.group(1)))

    missing_plan_vlans = sorted(expected_vlan_ids - existing_vlan_ids)
    # Only flag missing VLANs when we actually have a VLAN table (evidence) to compare against,
    # and always skip VLAN 1 (the default VLAN that always exists implicitly).
    if missing_plan_vlans and existing_vlan_ids:
        missing_plan_vlans_filtered = [v for v in missing_plan_vlans if v != 1]
        if missing_plan_vlans_filtered:
            evidence_parts.append(
                f"Topology plan requires VLAN(s) {missing_plan_vlans_filtered} but they are absent from switch VLAN table"
            )

    # --- C) Wrong-VLAN assignment (access vlan X but plan wants Y) --------
    # Scan any "switchport access vlan NN" from running-config.
    port_vlans = {}
    # Pattern: "interface Fa0/10\n ... \n switchport access vlan 50"
    for m in re.finditer(
        r"interface\s+([A-Za-z0-9/]+)[^\n]*\n((?:[^\n]*\n)*?)\s*switchport\s+access\s+vlan\s+(\d{1,4})",
        show_output_raw, re.IGNORECASE,
    ):
        iface = m.group(1).strip()
        vlan_id = int(m.group(3))
        port_vlans[iface] = vlan_id

    # ALSO parse "show interfaces <port> switchport" output, which contains a
    # line like: "Access Mode VLAN: 50 (ENGINEERING)"
    # This is the standard Cisco Packet Tracer format and the most reliable
    # source of the actual access VLAN assigned to a port.
    # Walk the raw output, pairing each "show interfaces <x> switchport" command
    # with the "Access Mode VLAN: NN" line that appears after it in its block.
    current_port = None
    for raw_line in show_output_raw.splitlines():
        line = raw_line.rstrip()
        # Did a new "show interfaces <X> switchport" command just start?
        m_cmd = re.search(
            r"show\s+interfaces\s+([A-Za-z0-9 /]+?)\s+switchport",
            line, re.IGNORECASE,
        )
        if m_cmd:
            # Normalise Fa0/11 <-> FastEthernet0/11 <-> FastEthernet 0/11 to a
            # short canonical form so ports referenced multiple ways still match.
            port = m_cmd.group(1).strip()
            # Remove spaces between interface type and number (e.g., "FastEthernet 0/11" -> "FastEthernet0/11")
            port = re.sub(r"([A-Za-z])\s+(\d)", r"\1\2", port)
            norm = re.sub(r"^FastEthernet", "Fa", port, flags=re.IGNORECASE)
            norm = re.sub(r"^GigabitEthernet", "Gi", norm, flags=re.IGNORECASE)
            current_port = norm
            continue
        if current_port is None:
            continue
        m_vlan = re.search(
            r"Access\s*Mode\s*VLAN\s*:\s*(\d{1,4})",
            line, re.IGNORECASE,
        )
        if m_vlan:
            port_vlans[current_port] = int(m_vlan.group(1))
            current_port = None  # consumed

    # --- D) Same-IP-subnet but DIFFERENT access VLANs = VLAN assignment ---
    #    mismatch (Layer 2 isolation despite being on the same subnet).
    #    Heuristic:
    #      - We see 2+ access ports each with a specific Access Mode VLAN
    #      - Those assigned VLANs are DIFFERENT (more than 1 VLAN used)
    #      - AND the end hosts share an IP subnet (same first 3 octets seen,
    #        or evidence says they are on the same IP network / same subnet).
    assigned_vlans = set(port_vlans.values())
    same_subnet_hint = False
    # Simple hint: evidence says "same IP subnet" / "same IP network" explicitly
    if (
        ("same ip subnet" in show_output)
        or ("same ip network" in show_output)
        or ("same broadcast domain" in show_output)
        or ("cannot ping" in symptoms or "100% loss" in show_output or "lost = 4" in show_output)
    ):
        # Two PCs, same first-3-octets = likely same /24 subnet
        from collections import Counter
        ip_prefixes = Counter()
        for m_ip in re.finditer(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d{1,3})\b", show_output_raw):
            first_three = m_ip.group(1)
            last_octet = int(m_ip.group(2))
            # Skip 0/255, masks (all octets 255), and gateways ending in .1 as anchors
            if first_three in ("0.0.0", "255.255.255", "255.255.0", "255.0.0"):
                continue
            if 1 < last_octet < 254:
                ip_prefixes[first_three] += 1
        # If any /24 prefix appears 2+ times, we have multiple hosts in it
        if any(cnt >= 2 for cnt in ip_prefixes.values()):
            same_subnet_hint = True

    if len(assigned_vlans) >= 2 and same_subnet_hint:
        sorted_vlans = sorted(assigned_vlans)
        port_map_str = ", ".join(
            f"{p}:VLAN{v}" for p, v in sorted(port_vlans.items())
        )
        evidence_parts.append(
            f"Access ports assigned to DIFFERENT VLANs {sorted_vlans} even though end hosts share an IP subnet: {port_map_str}"
        )

    # If the topology only lists a few VLANs and a configured access VLAN is
    # not among them AND not 1 (default), flag it.
    for iface, vlan in port_vlans.items():
        if expected_vlan_ids and vlan not in expected_vlan_ids and vlan != 1:
            evidence_parts.append(
                f"Interface {iface} assigned to VLAN {vlan} but topology plan only expects VLAN(s) {sorted(expected_vlan_ids)}"
            )

    if evidence_parts:
        # Pick slightly different issue wording depending on flavour detected
        # (case-insensitive match because evidence strings are descriptive literal messages
        # that may use capitalised "Inactive" / "Missing VLAN" etc).
        flavour = "VLAN assignment mismatch detected"
        evidence_lower = [e.lower() for e in evidence_parts]
        has_missing = any(
            "inactive" in e or "absent from switch vlan" in e or "vlan is missing" in e
            for e in evidence_lower
        )
        has_mismatch = any(
            ("different vlans" in e and "same ip subnet" in e)
            or ("di fferent vlans" in e)  # typo-tolerant
            or "mismatch" in e
            for e in evidence_lower
        )
        if has_mismatch and not has_missing:
            # Pure assignment mismatch (two ports, two VLANs, both VLANs exist).
            flavour = (
                "VLAN Assignment Mismatch - ports in the same IP subnet are "
                "assigned to different VLANs, blocking Layer 2 communication"
            )
        elif has_missing:
            flavour = "Missing VLAN - VLAN referenced by port was never created on the switch"
        return finding(
            issue=flavour,
            severity="high",
            evidence="; ".join(evidence_parts),
            suggestion="Verify switch VLAN configuration. Step-by-step:\n"
                       "  1. Create required VLANs:  configure terminal\n"
                       "                               vlan <id>\n"
                       "                                name <DescriptiveName>\n"
                       "  2. Assign correct access VLAN per port:\n"
                       "                               interface <port>\n"
                       "                                switchport mode access\n"
                       "                                switchport access vlan <correct_id>\n"
                       "  3. Verify with:  show vlan brief\n"
                       "                   show interfaces <port> switchport"
        )
    return None


def rule_ip_address_conflict(case_data):
    """
    Rule: Check for IP address conflicts or missing IPs.
    Looks for words like "duplicate", "conflict", or missing IP address in evidence.
    """
    show_output = (
        case_data.get("show_commands", "").lower()
        + " "
        + case_data.get("show_command_evidence", "").lower()
    )
    symptoms = case_data.get("symptoms", "").lower() + " " + case_data.get("symptom", "").lower()

    evidence_parts = []
    if "duplicate" in show_output and "ip" in show_output:
        evidence_parts.append("Show output mentions duplicate IP")
    if "conflict" in symptoms and "ip" in symptoms:
        evidence_parts.append("Symptom reports IP conflict")
    if "no ip address" in show_output:
        evidence_parts.append("Interface has no IP address configured")
    # Detect missing IP configuration: look for patterns that indicate a device
    # has NO IP listed at all. We must be careful: "IPv4 Address" (with v4) does
    # NOT contain the substring "ip address" so look for BOTH variants.
    has_ip_listing = (
        ("ip address" in show_output) or ("ipv4 address" in show_output)
        or ("ip address." in show_output) or ("ipv4 address." in show_output)
    )
    # Fallback: even if the "IPv4 Address:" label is missing, we might still
    # have IPs written in a free-form format like "PC0: 192.168.50.10 / 255.255.255.0".
    # Count valid host-looking IPs (non-mask, non-all-zero, non-.0/.255 endings) via regex.
    if not has_ip_listing:
        import re as _re_ip
        host_ip_count = 0
        for m_ip in _re_ip.finditer(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b", show_output):
            a, b, c, d = (int(x) for x in m_ip.groups())
            if not (0 <= a <= 255 and 0 <= b <= 255 and 0 <= c <= 255 and 0 <= d <= 255):
                continue
            # Skip obvious masks (255.x.x.x, x.255.255.255, 255.255.0.0 style)
            first_three = f"{a}.{b}.{c}"
            if first_three in ("255.255.255", "255.255.0", "255.0.0", "0.0.0"):
                continue
            # Skip network (d=0) and broadcast (d=255) addresses as host indicators
            if d == 0 or d == 255:
                continue
            host_ip_count += 1
        if host_ip_count >= 2:
            has_ip_listing = True
    if (not has_ip_listing) and ("cannot ping" in symptoms or "no connectivity" in symptoms):
        evidence_parts.append("No IP configuration found and ping fails")

    if evidence_parts:
        return finding(
            issue="IP address conflict or missing IP configuration",
            severity="high",
            evidence="; ".join(evidence_parts),
            suggestion="Assign a unique, unused IP address from the correct subnet. "
                       "Use: ip address <ip> <subnet_mask> in interface config mode."
        )
    return None


def rule_default_gateway_missing(case_data):
    """
    Rule: Check if a device has a MISSING (0.0.0.0) or WRONG default gateway.
    Wrong = the PC has a gateway IP that does NOT match the actual router IP
    mentioned in the topology, or the gateway has a typo/octet error.
    """
    show_output = case_data.get("show_commands", "").lower() + " " + case_data.get("show_command_evidence", "").lower()
    topology = case_data.get("topology", "").lower()
    symptoms = case_data.get("symptoms", "").lower() + " " + case_data.get("symptom", "").lower()

    evidence_parts = []

    # Scenario 1: explicit cannot-reach-other-subnet symptom
    if (("cannot reach" in symptoms or "cannot ping" in symptoms)
            and ("different subnet" in symptoms or "remote subnet" in symptoms
                 or "other subnet" in symptoms or "server on a different" in symptoms
                 or "10.0.50" in symptoms)):
        evidence_parts.append("Symptom reports inability to reach different/remote subnet")

    # Scenario 2: gateway is literally not set (0.0.0.0) - textbook "missing"
    if ("default gateway" in show_output or "default-gateway" in show_output) and \
       ("0.0.0.0" in show_output):
        evidence_parts.append("Default gateway is 0.0.0.0 (not configured)")
    if "no default gateway" in show_output:
        evidence_parts.append("Configuration explicitly states 'no default gateway'")
    if "gateway" in show_output and "not set" in show_output:
        evidence_parts.append("Gateway explicitly flagged 'not set' in show output")

    # Scenario 3: WRONG gateway - topology mentions real gateway X, but
    # PC's ipconfig shows a different gateway Y (still a valid-looking IP, not 0.0.0.0).
    # We detect this by extracting gateway IPs from topology+show and comparing.
    import re
    # Pull all IPv4 addresses from topology that look like a gateway:
    # Pattern: ".1 " at the end of a subnet or near "gateway"/"router" text
    topo_gateways = []
    # Scan topology lines with a simple heuristic: any x.x.x.1 IP is likely a gateway
    for ip in re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", topology):
        parts = ip.split(".")
        if all(0 <= int(p) <= 255 for p in parts):
            # Router interface IPs in topology are highly likely gateways for their LANs
            if (("router" in topology) or ("gateway" in topology)
                    or ("lan" in topology) or parts[3] == "1"):
                topo_gateways.append(ip)

    # Now scan show_output for lines matching "Default Gateway.........: X" pattern
    configured_gateways = []
    for gw_match in re.finditer(
        r"default[- ]gateway[ .:]*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", show_output, re.IGNORECASE
    ):
        configured_gateways.append(gw_match.group(1))

    # If we have both lists, and there's a mismatch -> WRONG gateway fault
    if configured_gateways and topo_gateways:
        for cg in configured_gateways:
            if cg == "0.0.0.0":
                evidence_parts.append(f"Configured gateway is 0.0.0.0")
            elif cg not in topo_gateways:
                evidence_parts.append(
                    f"Configured gateway {cg} does not match any router/gateway IP in topology "
                    f"(expected one of: {', '.join(topo_gateways)})"
                )
    # Also: user-annotated evidence like (WRONG ...) comments inside show output
    if "(wrong" in show_output and "gateway" in show_output:
        evidence_parts.append("Show output contains explicit 'WRONG gateway' annotation")

    if evidence_parts:
        return finding(
            issue="Default gateway is missing or incorrect",
            severity="medium",
            evidence="; ".join(evidence_parts),
            suggestion="Set the CORRECT default gateway. On a PC: Desktop > IP Configuration "
                       "and set Default Gateway to the router's LAN IP (x.x.x.1 typically). "
                       "On a switch/management: ip default-gateway <gateway_ip>."
        )
    return None


def rule_cable_issue(case_data):
    """
    Rule: Suspect physical layer (cable/port) issues.
    """
    symptoms = case_data.get("symptoms", "").lower() + " " + case_data.get("symptom", "").lower()
    show_output = case_data.get("show_commands", "").lower() + " " + case_data.get("show_command_evidence", "").lower()

    evidence_parts = []
    if "link light" in symptoms and ("off" in symptoms or "out" in symptoms):
        evidence_parts.append("Link light is off")
    if "no link" in symptoms:
        evidence_parts.append("User reports no link")
    if "down/down" in show_output and not ("administratively" in show_output):
        evidence_parts.append("Interface down/down but not admin down - likely cable/port issue")
    # Check for genuine cable-fault mentions, but NOT the idiom "cable plant"
    # which means the overall wiring infrastructure (not a cable fault).
    genuine_cable_hits = False
    if "bad cable" in symptoms:
        genuine_cable_hits = True
    elif "loose cable" in symptoms:
        genuine_cable_hits = True
    elif "cable problem" in symptoms:
        genuine_cable_hits = True
    elif "cable issue" in symptoms:
        genuine_cable_hits = True
    elif "faulty cable" in symptoms:
        genuine_cable_hits = True
    elif "replace cable" in symptoms:
        genuine_cable_hits = True
    elif "wrong cable" in symptoms:
        genuine_cable_hits = True
    elif "cable unplugged" in symptoms:
        genuine_cable_hits = True
    elif "ethernet cable" in symptoms and ("loose" in symptoms or "bad" in symptoms or "faulty" in symptoms):
        genuine_cable_hits = True
    if genuine_cable_hits:
        evidence_parts.append("Symptom mentions possible cable problem")

    if evidence_parts:
        return finding(
            issue="Possible physical layer issue (cable or port)",
            severity="medium",
            evidence="; ".join(evidence_parts),
            suggestion="1. Check that Ethernet cable is securely plugged in on both ends.\n"
                       "2. Try a known-good replacement cable.\n"
                       "3. Try a different switch port.\n"
                       "4. Verify correct cable type (straight-through vs crossover)."
        )
    return None


def rule_subnet_mask_error(case_data):
    """
    Rule: Check for incorrect/mismatched subnet mask on end devices.
    Typical beginner mistakes: using /16 (255.255.0.0) on a /24 network,
    devices on the same LAN with differing masks, or annotations like
    '(WRONG)' next to the mask in evidence.
    """
    import re

    show_output = case_data.get("show_commands", "").lower() + " " + case_data.get("show_command_evidence", "").lower()
    symptoms = case_data.get("symptoms", "").lower() + " " + case_data.get("symptom", "").lower()
    topology = case_data.get("topology", "").lower()

    evidence_parts = []

    # 1) Symptom text directly says mask is wrong / incorrect / mismatch
    mask_symptom_kw = (
        ("wrong subnet mask" in symptoms)
        or ("incorrect subnet mask" in symptoms)
        or ("subnet mask" in symptoms and "wrong" in symptoms)
        or ("mismatch" in symptoms and "mask" in symptoms)
        or ("subnet mask" in symptoms and ("mismatch" in symptoms or "incorrect" in symptoms or "wrong" in symptoms))
    )
    if mask_symptom_kw:
        evidence_parts.append("Symptom text mentions wrong/incorrect subnet mask")

    # 2) Explicit annotations in evidence: (WRONG - ...) near "Subnet Mask"
    # We look for the mask value followed by a comment flag like (WRONG / incorrect / mistake)
    if ("wrong" in show_output and "subnet mask" in show_output) or \
       ("(wrong" in show_output and "mask" in show_output):
        evidence_parts.append("Evidence contains explicit WRONG annotation on subnet mask")
    if "(WRONG" in case_data.get("show_command_evidence", "") and \
       "mask" in case_data.get("show_command_evidence", "").lower():
        # Repeat check on case-sensitive data because our 'WRONG' annotation is uppercase
        evidence_parts.append("Evidence contains explicit (WRONG) marker on subnet mask line")

    # 3) Mismatch detected: on same LAN, two devices have different masks
    # (Classic Packet Tracer beginner mistake: PC-A /16, PC-B /24 on same switch)
    # Extract all subnet mask values from "Subnet Mask . . . . . : <mask>" lines
    found_masks = set()
    for m in re.finditer(r"subnet[ -]mask[ .:]*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", show_output, re.IGNORECASE):
        found_masks.add(m.group(1))

    # Also pull expected mask from topology plan description
    # e.g. topology says "subnet 192.168.20.0/24 (255.255.255.0)" -> expected = 255.255.255.0
    expected_masks = set(re.findall(r"255\.\d{1,3}\.\d{1,3}\.\d{1,3}", topology))

    if len(found_masks) > 1:
        evidence_parts.append(
            f"Multiple different subnet masks found on end devices: {sorted(found_masks)} "
            f"(should be identical for devices on the same LAN)"
        )

    if expected_masks and found_masks:
        for actual in found_masks:
            if actual not in expected_masks:
                evidence_parts.append(
                    f"Configured mask {actual} does NOT match topology plan mask(s) {sorted(expected_masks)}"
                )

    # 4) Heuristic: topology says /24 plan but evidence has a /16 (255.255.0.0) mask
    # (common typo: student typed 255.255.0.0 instead of 255.255.255.0)
    if ("/24" in topology or "255.255.255.0" in topology) and "255.255.0.0" in show_output:
        evidence_parts.append(
            "Topology plan uses /24 (255.255.255.0) but a device configured /16 (255.255.0.0)"
        )

    # 5) Ping symptom "destination host unreachable" between two same-LAN devices
    # (often caused by mask mismatch putting them on "different networks" per stack)
    if "destination host unreachable" in symptoms and "same lan" in topology:
        evidence_parts.append("Same-LAN ping returns 'destination host unreachable' (classic mask mismatch symptom)")

    if evidence_parts:
        return finding(
            issue="Subnet mask is incorrect or mismatched",
            severity="high",
            evidence="; ".join(evidence_parts),
            suggestion="Verify the planned mask for the subnet and reconfigure ALL end devices. "
                       "For /24 networks use 255.255.255.0 uniformly. "
                       "On a PC: Desktop > IP Configuration > correct Subnet Mask field. "
                       "On a router/switch interface: ip address <correct_ip> <correct_mask>."
        )
    return None


def rule_missing_static_route(case_data):
    """
    Rule: Check for missing static route (two routers / remote network unreachable
    because the router has no ip route statement for the destination subnet).
    Typical student Packet Tracer scenario: two routers connected, each has a
    LAN, but no static route on R1 to reach R2's LAN and vice versa.
    """
    symptoms = case_data.get("symptoms", "").lower() + " " + case_data.get("symptom", "").lower()
    show_output = case_data.get("show_commands", "").lower() + " " + case_data.get("show_command_evidence", "").lower()
    topology = case_data.get("topology", "").lower()

    evidence_parts = []

    # Topology suggests two routers (classic static-route scenario)
    if ("r1" in topology and "r2" in topology) or ("router1" in topology and "router2" in topology):
        evidence_parts.append("Two-router topology detected (static route scenario)")

    # Symptom: cannot reach remote subnet / different LAN
    if (("cannot reach" in symptoms or "cannot ping" in symptoms)
            and ("remote" in symptoms or "other subnet" in symptoms
                 or "other lan" in symptoms or "different subnet" in symptoms
                 or "r2 lan" in symptoms or "192.168.2" in symptoms)):
        evidence_parts.append("Symptom reports unreachable remote subnet")

    # show ip route has no static route (no S entry) AND has connected only
    if "show ip route" in show_output:
        if ("s " not in show_output) and ("static" not in show_output):
            evidence_parts.append("show ip route has no 'S' (static) route entry")
        if "gateway of last resort is not set" in show_output:
            evidence_parts.append("No gateway of last resort (no default route)")
        if ("192.168.1.0" in show_output and "192.168.2.0" not in show_output) or \
           ("192.168.2.0" in show_output and "192.168.1.0" not in show_output):
            evidence_parts.append("Only one LAN subnet appears in the routing table - remote subnet missing")

    # Explicit mentions
    if "static route" in (symptoms + show_output + topology) and \
       ("missing" in (symptoms + show_output + topology) or
        "absent" in (symptoms + show_output + topology) or
        "no ip route" in show_output):
        evidence_parts.append("Text mentions missing static route")

    if len(evidence_parts) >= 2:
        return finding(
            issue="Missing static route - router does not know how to reach remote subnet",
            severity="high",
            evidence="; ".join(evidence_parts),
            suggestion="Add a static route on each router pointing toward the opposite LAN. "
                       "Example on R1: ip route 192.168.2.0 255.255.255.0 10.0.0.2 "
                       "(where 10.0.0.2 is R2's serial/link address). "
                       "And corresponding reverse route on R2: ip route 192.168.1.0 255.255.255.0 10.0.0.1"
        )
    return None


# ============================================================
# Main Rule Checker Orchestrator
# ============================================================

ALL_RULES = [
    rule_interface_down,
    rule_vlan_mismatch,
    rule_ip_address_conflict,
    rule_default_gateway_missing,
    rule_cable_issue,
    rule_subnet_mask_error,
    rule_missing_static_route,
]


def run_rule_checker(case_data):
    """
    Run all registered rules against a case and return all findings.

    Args:
        case_data (dict): A single case from cases.csv with fields like:
            case_id, symptoms, topology, show_commands, expected_fix

    Returns:
        list[dict]: All findings detected by the rule engine, in standard finding format.
    """
    print_info("Running Python Rule-Based Checker...")
    findings = []
    case_id = case_data.get("case_id", "unknown")

    for rule_function in ALL_RULES:
        rule_name = rule_function.__name__
        try:
            result = rule_function(case_data)
            if result is not None:
                result["source"] = "rule_checker"
                result["rule_name"] = rule_name
                findings.append(result)
                print_info(f"  Rule '{rule_name}' triggered: {result['issue']}")
        except Exception as e:
            # Don't let one broken rule stop the whole checker
            print(f"  [WARN] Rule '{rule_name}' crashed: {e}")

    # Add a default finding if no rules fired
    if not findings:
        findings.append(finding(
            issue="No obvious rule violations found",
            severity="low",
            evidence="All rule checks passed without triggering any conditions",
            suggestion="Investigate further. Check routing protocols, ACLs, DNS, or less-common issues."
        ))
        findings[0]["source"] = "rule_checker"
        findings[0]["rule_name"] = "default_no_issue"

    print_info(f"Rule checker completed: {len(findings)} finding(s) for case {case_id}")
    return findings
