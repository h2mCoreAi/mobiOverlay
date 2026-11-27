# 07 Muse reply (Muse Spark 1.3, 2026-11-27)

Reply to the reputation-template prompt. **Condensed by Claude:** thresholds
that repeat 05/06 are summarized; everything new or conflicting is kept. Muse
searched the web, and almost every row cites a specific mission page in the
api.star-citizen.wiki database pinned to `version=4.10.3-LIVE.13165946`, the
most precise sourcing of any AI.

## Header

- MODEL: Muse Spark 1.3 | WEB SEARCH USED: yes | DATE: 2026-11-27
- 5.0 STATUS: PTU | build 5.0.0-PTU.13284307 | live date unknown | wipe unknown

## Name notes from Muse

- "Covalex Independent Contractors" is the mission-giver name; the faction is
  Covalex Shipping.
- Crusader Security missions credit Crusader Industries; Hurston Security
  credits Hurston Dynamics; MT Protection Services credits microTech. These use
  the Contractor ladder for standing.
- Northrock has two ladders: a Security / Mercenary Guild bounty ladder
  (Applicant 0 to Elite Security Contractor 1,600,000) and a Contractor
  standing ladder (0 to 95,250).
- Every hauling ladder has a "Not Eligible" rank at -1,000 below Trainee.
- Rough & Ready: no ladder; its missions give no reputation
  ([verse-base](https://verse-base.com/missionen.html)).

## Same thresholds as Grok and ChatGPT

Hauling, Bounty Hunters Guild, Contractor, Security, Recco Battaglia and
Wikelo ladders: identical numbers (see 00-findings.md).

## New unlock details (api.star-citizen.wiki, 4.10.3)

- **Covalex hauling by rank:** Trainee: Extra Small, Direct. Rookie: Extra
  Small and Small, Direct and Planetary. Junior: Small and Medium, Direct and
  Planetary. **Member: Interstellar Hauls**, Small and Medium, Solar.
  Experienced: Large Hauls; Medium max container 16 SCU.
- **InterSec:** Neutral: New Defense Contract: Elimination. Sr. Contractor:
  Tactical Strike Group Needed.
- **Foxwell:** Jr. Contractor: Yellow Level Contract: Security Sweep.
  Contractor: Orange Level Contract: Security Patrol. Sr. Contractor: Orange
  Level Contract: Potential Security Threat. Veteran: Red Level Contract:
  High-Risk Security Patrol.
- **Adagio:** Neutral: Salvage Introduction. Sr. Contractor: larger paid
  salvage claims.
- **Recco Battaglia:**
  - Prospective Associate: Welcome to the System; Clearcut Module blueprint.
  - Associate: Emergency: Blinding Hope in Trouble; Deluge and Overrun Module
    blueprints.
  - Trusted Associate: Idea for Isaac; GOLEM MC-4 and MISC Enhanced Ore Pod
    blueprints.
  - Prestige 1: Extra Special Job (Drake Golem Alliance). Prestige 2: MISC
    Prospector Alliance. Prestige 3: ARGO MOLE Alliance.
- **Vaughn:** Neutral: A Chance to Impress. Listed in Nyx.
- **Headhunters and Dead Saints:** Contractor standing ladder, with mission
  pages as sources.
- **BHG licenses:** Probationary VLRT, Junior LRT, Guild Member MRT
  (Tracker License), Senior HRT, Veteran VHRT, Steward ERT.

## 5.0 reputation changes (sourced)

- Guild reputation as a second layer; career contracts need and raise both.
  [RSI Patch Watch](https://robertsspaceindustries.com/spectrum/community/SC/forum/3/thread/alpha-5-0-patch-watch-new-horizons-new-opportuniti)
- Career Contract Boards (per-faction tabs in Guild Halls, e.g. Mercenary
  Guild, Interstellar Transport Guild) vs Notice Boards (credits only, no rep).
  (Patch Watch)
- Contract scope (local / regional / global / system) shown in Contract
  Manager and on boards; reputation scopes for Cornerstone, Hockrow, Ling and
  BHG. [RSI 5.0 PTU notes](https://robertsspaceindustries.com/spectrum/community/SC/forum/190048/thread/star-citizen-alpha-5-0-ptu-patch-notes/9232177)
- Covalex and FTL career board ranks; Transport Guild intro mission required;
  new Wikelo ship contracts; High Risk bounties give 4,000 rep instead of
  2,000. [Orvix Grid](https://www.orvixgrid.com/next-patch)
- Guild rank pages show names and icons for the first six ranks.
  [starzen.space](https://www.starzen.space/t/sc-patch-notes/19320/1721)
- PTU-only rep multiplier, rising per build. (Orvix Grid)

## Claude's review

- Resolves two conflicts: Headhunters and Dead Saints have Contractor
  standing (mission pages prove it), and Recco's "Emergency" and "Idea for
  Isaac" are missions, not ranks.
- Opens one: Muse says Covalex **Member** unlocks Interstellar Hauls;
  starcitizen.tools (via Grok) says **Master**.
- Adds to the BHG license conflict on the starcitizen.tools side (see
  00-findings.md).
