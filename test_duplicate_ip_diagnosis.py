"""
TEST: Duplicate IP evidence is correctly diagnosed as 'Duplicate IP Address'
by the new evidence-based Mock AI.

This test is EVIDENCE-BASED, not case-ID based. We build THREE synthetic cases
in-memory with duplicate-IP patterns, and verify:
  1) root_cause == 'Duplicate IP Address'
  2) confidence == 'High'
  3) osi_layer == 'Layer 3'
  4) next_command == 'Check IP configuration on all connected hosts'
  5) fix_steps mentions unique unused IP address
Additionally, a case that ONLY has the word 'mask' but no actual mismatch MUST
NOT return a subnet mask false-positive (the bug that motivated this rewrite).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from ai_diagnosis import _mock_ai_keyword_analysis

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  [PASS] {name}")
        PASS += 1
    else:
        print(f"  [FAIL] {name}  {detail}")
        FAIL += 1

print("="*60)
print("  TEST: Duplicate IP diagnosis (evidence-based)")
print("="*60)

# --- Case A: matches C001 Packet Tracer evidence (actual user data) ------------
case_c001_like = {
    "symptom": "PC-A and PC-B both report Windows has detected an IP address conflict. Intermittent ping.",
    "topology": "1x 2960 switch S1, 2x Generic PCs (PC-A, PC-B). Same LAN 192.168.10.0/24.",
    "show_command_evidence": (
        "[ACTUAL PACKET TRACER EVIDENCE]\n"
        "PC0> ipconfig\n"
        "IPv4 Address: 192.168.1.10\n"
        "Subnet Mask: 255.255.255.0\n"
        "\n"
        "PC1> ipconfig\n"
        "IPv4 Address: 192.168.1.10\n"
        "Subnet Mask: 255.255.255.0\n"
        "[/ACTUAL PACKET TRACER EVIDENCE]"
    ),
}

print("\n[Scenario A] C001-style: PC0 and PC1 both 192.168.1.10")
findings_a = _mock_ai_keyword_analysis(case_c001_like)
top_a = findings_a[0]
check("At least 1 finding returned", len(findings_a) >= 1)
check("First finding root_cause = 'Duplicate IP Address'",
      top_a.get("root_cause") == "Duplicate IP Address",
      f"got: {top_a.get('root_cause')!r}")
check("confidence = 'High'", top_a.get("confidence") == "High",
      f"got: {top_a.get('confidence')!r}")
check("osi_layer = 'Layer 3'", top_a.get("osi_layer") == "Layer 3",
      f"got: {top_a.get('osi_layer')!r}")
check("next_command mentions checking IP config on all hosts",
      "ip configuration on all connected hosts" in top_a.get("next_command","").lower(),
      f"got: {top_a.get('next_command')!r}")
check("fix_steps says unique unused IP then re-test",
      "unique unused ip address" in top_a.get("fix_steps","").lower() and
      "test connectivity again" in top_a.get("fix_steps","").lower(),
      f"got: {top_a.get('fix_steps')!r}")
check("Issue text mentions 'Duplicate IP Address' phrase",
      "duplicate ip address" in top_a.get("issue","").lower())
check("Evidence string names both devices and the IP",
      "192.168.1.10" in top_a.get("evidence","") and
      ("PC0" in top_a.get("evidence","") or "pc0" in top_a.get("evidence","").lower()))
# C001 false-positive regression: must NOT also diagnose subnet mask issue
wrong_mask_findings = [f for f in findings_a if "subnet mask" in f.get("issue","").lower() and "Duplicate IP" not in f.get("root_cause","Duplicate IP")]
check("No false-positive 'subnet mask' finding returned (regression guard)",
      len(wrong_mask_findings) == 0,
      f"False-positive subnet mask findings: {[f['issue'] for f in wrong_mask_findings]}")


# --- Case B: Two laptops in Packet Tracer using 'IP Address..... : x.x.x.x' old format ---
case_old_format = {
    "symptom": "Same IPv4 address is configured on two different devices. Conflict warnings on screen.",
    "topology": "Switch0, two laptops. 10.0.0.0/24 subnet.",
    "show_command_evidence": (
        "LAPTOP-A> ipconfig\n"
        "\n"
        "IP Address. . . . . . . . . . . . : 10.0.0.55\n"
        "Subnet Mask . . . . . . . . . . . : 255.255.255.0\n"
        "\n"
        "LAPTOP-B> ipconfig\n"
        "\n"
        "IP Address. . . . . . . . . . . . : 10.0.0.55\n"
        "Subnet Mask . . . . . . . . . . . : 255.255.255.0\n"
        "\n"
        "Switch0# show logging\n"
        "*Jun  5 09:12:34.567: %IP-4-DUPADDR: Duplicate address 10.0.0.55 on Vlan1, sourced by aabb.ccdd.eeff\n"
    ),
}
print("\n[Scenario B] Old-format ipconfig + %IP-4-DUPADDR syslog")
findings_b = _mock_ai_keyword_analysis(case_old_format)
top_b = findings_b[0]
check("root_cause Duplicate IP Address", top_b.get("root_cause") == "Duplicate IP Address")
check("confidence High", top_b.get("confidence") == "High")
check("osi_layer Layer 3", top_b.get("osi_layer") == "Layer 3")
check("conflict keyword counted (LAPTOP-A and LAPTOP-B share same IP)",
      "10.0.0.55" in top_b.get("evidence",""))


# --- Case C: Duplicate detected via explicit phrases + frequency (no device labels) ---
case_freq = {
    "symptom": "Duplicate IP, same IP on two different devices, conflict warnings.",
    "topology": "Server and PC connected via switch.",
    "show_command_evidence": (
        "Server IP: 172.16.0.99 / 255.255.0.0 / GW 172.16.0.1\n"
        "Printer IP: 172.16.0.99 / 255.255.0.0 / GW 172.16.0.1\n"
    ),
}
print("\n[Scenario C] Duplicate detected by frequency + duplicate phrases")
findings_c = _mock_ai_keyword_analysis(case_freq)
has_dup = any(f.get("root_cause") == "Duplicate IP Address" for f in findings_c)
check("Duplicate IP finding appears", has_dup)
dup_c = next(f for f in findings_c if f.get("root_cause") == "Duplicate IP Address")
check("Duplicate IP mentions 172.16.0.99", "172.16.0.99" in dup_c.get("evidence","") or "172.16.0.99" in dup_c.get("issue",""))


# --- Regression test: case that ONLY has the word "Subnet Mask" with matching masks ---
#     MUST NOT return a subnet mask false-positive.
mask_only = {
    "symptom": "Everything works but student just ran ipconfig for homework.",
    "topology": "1 PC on LAN 192.168.1.0/24, gateway 192.168.1.1, mask 255.255.255.0",
    "show_command_evidence": (
        "PC> ipconfig\n"
        "IPv4 Address: 192.168.1.50\n"
        "Subnet Mask: 255.255.255.0\n"
        "Default Gateway: 192.168.1.1\n"
        "\n"
        "PC> ping 192.168.1.1\n"
        "Reply from 192.168.1.1: bytes=32 time<1ms TTL=255\n"
        "Reply from 192.168.1.1: bytes=32 time<1ms TTL=255\n"
        "(ping successful, no fault)\n"
    ),
}
print("\n[Regression] Healthy 'Subnet Mask' only -> no subnet mask false-positive")
findings_mask = _mock_ai_keyword_analysis(mask_only)
mask_false_pos = [f for f in findings_mask if "subnet mask" in f.get("issue","").lower() or f.get("root_cause") == "Wrong Subnet Mask"]
check("No subnet mask finding for healthy case (bug regression guard)",
      len(mask_false_pos) == 0,
      f"False-positive(s): {[f['issue'] for f in mask_false_pos]}")

print()
print("="*60)
print(f"  RESULT: {PASS} passed, {FAIL} failed out of {PASS+FAIL}")
print("="*60)
if FAIL > 0:
    sys.exit(1)
