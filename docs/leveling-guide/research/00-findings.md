# Research findings so far (2026-11-27)

What the AI replies in this folder agree on, what conflicts, and what is still
missing. Source files: 01 Gemini, 02 DeepSeek, 03 Muse (summary only),
04-05 Grok, 06 ChatGPT, 07 Muse (full reply), 08 Gemini (second run),
09 Claude on claude.ai (copied as received).

## Reliability

| AI | Verdict |
|----|---------|
| Grok (04, 05) | Best by far. Searched the web, cited every row, flagged its own conflicts. Rank data comes from sites that read the game files (Citadel, Dystopian Dynasty), labeled 4.10.2. |
| Muse (07) | Equal to Grok. Every row cites a mission page in the star-citizen.wiki database pinned to the 4.10.3 build. Best per-rank unlock detail. |
| ChatGPT (06) | Close behind. Cited every row. Its thresholds come from CCU Ladder's 4.10.3 live game data (pulled 2026-11-16) and match Grok's exactly. Its Stanton security ladders are outdated. |
| Muse (03) | Same numbers as Grok, but only a summary came back; its sources were not passed on. |
| Claude web (09) | Good. Sourced rows plus a "guide notes" section: intro missions, rep loss, cross-faction rules, scrip per rank. Cites the slightly older PTU build 13273298. |
| Gemini (08) | Second run, new chat: good. Mission-page sources for every row; most unlock detail for minor factions. |
| Gemini (01) | First run: good activity overview and first steps. Many ranks "unknown"; several broken source links; confused Recco Battaglia mission names with ranks. |
| DeepSeek (02) | No sources, contradicts itself. Only useful where others agree. |

## Settled (multiple sources agree)

- **Live patch:** 4.10.3, released 2026-11-12 (build 4.10.3-LIVE.13165946;
  client hotfix 13220821 on 2026-11-19).
- **5.0:** PTU, open to all backers, build 5.0.0-PTU.13284307 (2026-11-25). No
  live date. No wipe planned (CIG staff). PTU reputation multiplier (50x) won't
  be on live.
- **Reputation ladders** (cumulative rep, from game data):
  - Contractor: Neutral 0, Jr. Contractor 800, Contractor 2,200,
    Sr. Contractor 5,800, Veteran 15,000, Head 38,000, Elite 95,250.
    Used by most factions (InterSec, Foxwell, Adagio, Headhunters, CFP, Vaughn,
    Dead Saints, Shubin, Hockrow and more).
  - Hauling: Trainee 0, Rookie 50, Junior 250, Member 5,250,
    Experienced 27,750, Senior 77,750, Master 237,750 (Covalex, Red Wind, Ling,
    UDM, FTL).
  - Bounty Hunters Guild: Applicant 0, Probationary 1, Junior 3,000,
    Guild Member 10,000, Senior 40,000, Veteran 200,000, Guild Steward 480,000.
    Each rank sells a license for the next target tier (VLRT → ERT).
  - Security: Applicant 0 → Elite Security Contractor 1,600,000 (Hurston,
    Crusader, microTech, Northrock).
  - Recco Battaglia: Prospective Associate 0 → Prestige 3 69,600 (Prestige 1
    Golem, Prestige 2 Prospector, Prestige 3 MOLE).
  - Wikelo: New Customer 0, Very Good Customer 340, Very Best Customer 999.
  - Also: Courier, Bounty tracker, Hired Muscle, Assassin, Technician,
    Hover Time Trial (see 05).
- **Tutorial chain** (from the star-citizen.wiki mission database, stamped
  4.10.3): Your First Steps (15,000 aUEC), Your First Outing (15,000), Your
  First Flight (40,000). New accounts start with 20,000 aUEC.

- **Thresholds confirmed on 4.10.3:** ChatGPT's source (CCU Ladder, live data
  pulled 2026-11-16) gives the same numbers as Grok's 4.10.2 sources.

## Conflicts to resolve

- **HRT bounty rep 4,000 (up from 2,000):** Gemini says already on 4.10.3;
  Grok's source lists it as a 5.0 change.
- **BHG licenses per rank (mostly settled):** Probationary VLRT, Junior LRT,
  Guild Member MRT, Senior HRT, Veteran VHRT, Steward ERT. Backed by
  starcitizen.tools, Muse's and Gemini's mission pages (incl. a 4.10.3 page
  for the VHRT license). Only CCU Ladder / Versefiles skip MRT. Use this
  mapping; confirm in game when convenient.
- **Covalex interstellar hauls:** Muse and Claude web say Member unlocks
  "Interstellar / Solar" contracts; Gemini's mission pages show *large*
  interstellar hauls at Senior; Grok says Master. Likely reading: small and
  medium interstellar from Member, large interstellar from Senior, bulk at
  Master. Verify in game. Ling's interstellar hauls may start at Rookie.
- **Hired Muscle top ranks:** Grok: Rank IV 120,000, Rank VI 480,000 (III and
  V missing). Gemini (Tar Pits): III 30,000, IV 120,000, V 480,000,
  VI 1,600,000, the same shape as the Security ladder. Use Gemini's.
- **UDM:** Courier ladder (Applicant 0, Jr. Runner 1, Runner 2,500) per
  Gemini and Grok; Hauling ladder per ChatGPT and Muse. Probably both exist.
- **Foxwell:** Muse and Grok show Contractor standing with Yellow, Orange and
  Red contracts gated by rank; Versefiles (ChatGPT) gives Security rank names.
  Use the Contractor ladder.
- **Resolved:** Headhunters and Dead Saints do have Contractor standing (Muse
  cites their mission pages); Versefiles' "dossier only" means no separate
  career ladder. Recco's "Emergency" and "Idea for Isaac" are missions, not
  ranks.
- **Vaughn Assassin career:** Grok lists 6 ranks; ChatGPT lists 7 (adds
  "Assassin" between Low Level and High Value).
- **Stanton security/bounty ladders:** ChatGPT's names (e.g. "Elite Operative",
  "Legendary Bounty Hunter") come from old wiki pages; Grok's game-data names
  (Security and Tracker ladders) are current. Use Grok's.
- **Northrock:** Security ladder names (Citadel, CCU) or Tracker names
  (Dystopian Dynasty); same thresholds.
- **Hired Muscle:** Ranks III and V missing in the source.

## Still missing

- 5.0 guild rank thresholds and the full list of guilds.
- Per-rank unlocks for several factions (Ling, UDM, FTL, Dead Saints and others).
- How much rep a typical contract gives, per faction and tier. That turns rank
  thresholds into "about N contracts" counters. The star-citizen.wiki mission
  database lists rep per mission and is the best source for this.

## Guide mechanics (from 09, sourced there)

- **Intro missions** that start each ladder: Covalex "Opportunity for
  Independent Cargo Hauler"; Red Wind "Red Wind Seeking New Haulers"; Ling
  "Cargo Hauling Opportunity with Ling Hauling"; BHG Tracker Training Permit;
  InterSec "New Defense Contract: [TargetName] Elimination"; Adagio "Salvage
  Introduction"; Foxwell "Still Looking for Work?"; Recco "Welcome to the
  System" (Levski); Wikelo "Wikelo Arrive to System"; Dead Saints "Trial
  Cargo Haul"; Vaughn "A Chance to Impress".
- **Losing rep:** failing, abandoning or letting a contract expire can cost
  reputation (set per contract). Character Repair does not restore it.
  Rep is tracked per faction.
- **Cross-faction (Pyro):** Headhunters and Citizens for Prosperity gate some
  contracts on each other's standing; pick-a-side event contracts can wipe
  standing with the other side. The guide needs a warning before these.
- **Scrip rewards grow with rank:** Foxwell and CFP pay MG Scrip, Headhunters
  pay Council Scrip (x2 at Neutral up to x24 at Head Contractor).
- **Rep per contract (first data):** Recco 200-600 rep per contract, Prestige
  contracts once-only (800 each). Wikelo rep only from certain trades (e.g.
  30 rep). Wikelo favours: 50 MG Scrip, 50 Council Scrip, 50 Carinite or
  12 Grade AA pearls = 1 Favor.
- **Civilian Defense Force ladder:** Applicant 0, First Responder Trainee
  5,000, First Responder 20,000, Veteran First Responder 80,000.
- **Last full wipe:** 4.8 (2026-05-14). None announced for 5.0.
- **5.0 datamine (unconfirmed):** guild reputation may go to 50 ranks.

## Best sources found (use these directly from now on)

- **CCU Ladder** (cculadder.com): reputation thresholds and rank-gated
  contracts from 4.10.3 live game data.
- **api.star-citizen.wiki/missions**: per-mission database stamped
  4.10.3-LIVE.13165946, with rewards and reputation.
- **Versefiles** (versefiles.com/reputation): rank names from the game files.
- **Dystopian Dynasty** and **Citadel**: per-faction contract lists (4.10.2).
