# packet_tracer/ Directory

## Purpose

This folder is for your **Cisco Packet Tracer (.pkt)** files and the evidence you export
from them.

NetSage AI does NOT directly read `.pkt` files in Version 1. Instead, you manually
extract the relevant info from Packet Tracer and paste it into the `cases.csv` file
located in the `data/` folder.

---

## How to gather evidence from Packet Tracer

For each network fault scenario, collect **3 things**:

### 1. Symptoms
What is the user/student complaining about?
Examples:
- "PC1 cannot ping PC2"
- "No internet access from VLAN 20"
- "Link light is off on printer"

### 2. Topology
Brief description of the layout.
Example:
> "3 PCs on switch S1 in VLAN 10, connected to router R1 which routes to VLAN 20
>  with a server. IP range 192.168.1.0/24 (VLAN 10) and 192.168.2.0/24 (VLAN 20)."

### 3. Show command output
In Packet Tracer, run these commands on the relevant devices and paste the output:

**On switches/routers:**
```
enable
show running-config
show ip interface brief
show vlan brief
show interfaces trunk
show ip route
show interfaces <problem_port>
show logging
```

**On end devices (PCs/laptops/servers) use the Desktop > Command Prompt:**
```
ipconfig
ipconfig /all
ping <target_ip>
tracert <target_ip>
nslookup <hostname>   (if DNS relevant)
```

Then copy/paste the relevant chunks into the `show_commands` column in `data/cases.csv`.

---

## Suggested workflow for adding a new case

1. Build/save a broken network scenario in Packet Tracer: `my_scenario.pkt`
   (you can save the `.pkt` file in this folder)
2. Collect Symptoms, Topology, and Show Commands output
3. Add a new row to `../data/cases.csv`
4. Run `python ../src/main.py` to verify NetSage AI diagnoses it correctly
5. (Optional) Fix the network in Packet Tracer and save a "fixed" version of the .pkt
