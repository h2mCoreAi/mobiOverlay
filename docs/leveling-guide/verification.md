# Leveling Guide: claim verification (2026-11-27)

Every claim the AIs made (research files 01-09) that the guide could use was
checked against primary data before going into the guide. Only claims marked
**confirmed** are in the guide.

## Primary sources used

| Source | What it is | How it was read |
|--------|-----------|-----------------|
| [star-citizen.wiki mission API](https://api.star-citizen.wiki/api/missions) | Mission and faction data read from the game files. All 1,832 missions are stamped `4.10.3-LIVE.13165946` (the live build). | Downloaded in full (`/api/missions`, `/api/factions/<uuid>`) and queried offline. |
| RSI Knowledge Base | Official how-to articles: [Getting Started in the 'Verse](https://support.robertsspaceindustries.com/hc/en-us/articles/360025028633-Getting-Started-in-the-Verse), [Missions and Contracts](https://support.robertsspaceindustries.com/hc/en-us/articles/360008918933-Missions-and-Contracts) | Read in the browser (automated fetches get HTTP 403). |
| UEX Corp API | `vehicles_purchases_prices_all`: in-game ship prices, the same data source the overlay already uses | Live request. The module reads prices live instead of storing them. |

Mission data gives what the game is set to do. It doesn't show UI wording,
so menu steps are taken from the RSI articles.

## Reputation ladders

All confirmed from each faction's `reputation_ladder` in the game data
(4.10.3):

| Ladder | Ranks (reputation needed) | Used by |
|--------|---------------------------|---------|
| Standing (Contractor) | Hostile <0, Neutral 0, Jr. Contractor 800, Contractor 2,200, Sr. Contractor 5,800, Veteran Contractor 15,000, Head Contractor 38,000, Elite Contractor 95,250 | Adagio, ArcCorp, Bit Zeros, CFP, Civilian Defense Force, Clovus Darneely, Crusader Industries, Dead Saints, Eckhart, Foxwell, Headhunters, Highpoint, Hockrow, Hurston Dynamics, InterSec, microTech, Rayari, Ruto, Shubin, Tar Pits, Tecia Pacheco, UWC, Vaughn, Wallace Klim, XenoThreat |
| Hauling | Not Eligible -1,000, Trainee 0, Rookie 50, Junior 250, Member 5,250, Experienced 27,750, Senior 77,750, Master 237,750 | Covalex, Red Wind, Ling, UDM, FTL Courier |
| Bounty Hunting | Not Eligible -1,000, Applicant 0, Probationary Guild Member 1, Junior Guild Member 3,000, Guild Member 10,000, Senior Guild Member 40,000, Veteran Guild Member 200,000, Guild Steward 480,000 | Bounty Hunters Guild |
| Security | Applicant 0, Security Trainee 1, Jr. Security Contractor 5,000, Security Contractor 30,000, Sr. 120,000, Lead 480,000, Elite 1,600,000 | Northrock (main ladder); Security career of other factions |
| Recco Battaglia | Prospective Associate 0, Associate 2,400, Trusted Associate 6,000, Prestige 1 10,800, Prestige 2 30,000, Prestige 3 69,600 | Recco Battaglia |
| Wikelo | New Customer 0, Very Good Customer 340, Very Best Customer 999 | Wikelo Emporium |
| Technician | Applicant 0 … Master Technician 81,000 | Aciedo, Klescher |
| Mission-gate names | Courier: Jr. Runner 1, Runner 2,500. Bounty tracker: Tracker Trainee 1 … Master Tracker 1,600,000. Assassination: Assassin In Training 1 … Master Assassin 112,000. Hired Muscle: Rank I 1, II 5,000, III 30,000, IV 120,000 | seen in mission gates |

## Claims checked

| # | Claim (who made it) | Verdict | Evidence |
|---|---------------------|---------|----------|
| 1 | Live patch 4.10.3, build 13165946 (all) | **Confirmed** | every mission record carries `4.10.3-LIVE.13165946` |
| 2 | Start in New Babbage, Area18, Lorville or Orison (Gemini, Grok) | **Confirmed** | RSI KB Getting Started |
| 3 | New Player Experience tutorial offered after picking a city (Gemini, Grok) | **Confirmed** | RSI KB Getting Started |
| 4 | Tutorial chain Your First Steps / Outing / Flight (Grok) | **Confirmed** | mission records `Tutorial01..03` |
| 5 | Tutorial rewards 15,000 / 15,000 / **40,000** aUEC (Grok) | **Partly wrong** | Your First Flight pays **15,000**, not 40,000 ([record](https://api.star-citizen.wiki/missions/tutorial-your-first-flight-2)) |
| 6 | New accounts start with 20,000 aUEC (Gemini, Grok) | Not confirmed | only community sites; not in the guide |
| 7 | Ships retrieved at ASOP terminals; Flight Ready with U; request takeoff in mobiGlas Comms; N raises gear (Gemini) | **Confirmed** | RSI KB Getting Started |
| 8 | Contracts: F1, CONTRACTS app, Verified/Unverified, ACCEPT OFFER, SHARE with party (Gemini, Grok) | **Confirmed** | RSI KB Missions and Contracts |
| 9 | Set regeneration at a station clinic (Gemini) | Not confirmed | no source; wiki says imprints are made at a hospital; not in the guide |
| 10 | Covalex intro "Opportunity for Independent Cargo Hauler" (all) | **Confirmed** | Stanton version pays 50,250 aUEC, +50 Hauling rep (= Rookie) |
| 11 | Red Wind intro "Red Wind Seeking New Haulers" (Gemini, Claude) | **Confirmed** | +100 Hauling rep |
| 12 | Ling intro "Cargo Hauling Opportunity with Ling Hauling" (Claude) | **Confirmed** | +100 Hauling rep, Trainee only |
| 13 | Ling and Red Wind courier intros "Seeking New Contractors / Pilots" | **Confirmed** | +100 Courier rep, 5,000 / 5,750 aUEC |
| 14 | Hauling rep per contract by rank | **Confirmed (new)** | Trainee hauls +500, Rookie +50, Junior +500, Member +1,000, Experienced +2,000, Senior +4,000, Master +8,000 (Covalex) |
| 15 | Covalex unlocks interstellar at Member (Muse, Claude) / Senior (Gemini) / Master (Grok) | Not confirmed | no rank-titled Covalex interstellar contract in the data; not in the guide |
| 16 | Experienced opens Large hauls (Muse, Claude, Gemini) | **Confirmed** | "Experienced Rank - Large Cargo Haul" (+2,000) |
| 17 | BHG license order VLRT/LRT/MRT/HRT/VHRT/ERT by rank, MRT at Guild Member (Grok, Muse, Gemini, Claude) | **Confirmed** | certification missions: Training Permit (Applicant, 500 aUEC), Beginner's Permit (Junior, 1,000), Tracker License (Guild Member, 2,500), Journeyman (Senior, 5,000), Advanced (Veteran, 10,000), Master (Steward, 25,000) |
| 18 | CCU Ladder: MRT skipped (ChatGPT) | **Wrong** | Tracker License Certification is gated at Guild Member |
| 19 | HRT bounties give 4,000 rep (Gemini: 4.10.3; others: 5.0) | **Confirmed for 4.10.3** | HRT bounties +4,000 BHG rep in live data |
| 20 | Bounty rep per tier | **Confirmed (new)** | VLRT +500 (Hurston, Crusader) or +4,000 (microTech, ArcCorp); LRT +1,000; MRT +2,000; HRT +4,000; VHRT +8,000; ERT +16,000 |
| 21 | Foxwell intro "Still Looking for Work?" (Claude) | **Confirmed, incomplete** | the first contract is "Exciting New Opportunities with Foxwell Enforcement"; "Still Looking for Work?" follows it |
| 22 | Foxwell Red Level contracts from Veteran (Muse) | **Wrong** | Red Level contracts start at **Sr. Contractor** |
| 23 | InterSec intro "New Defense Contract: [TargetName] Elimination" (Muse, Claude) | **Confirmed** | Nyx, +100 |
| 24 | Vanduul-Tech Smugglers at Jr. Contractor (Gemini, Grok) | **Confirmed** | gated Jr. Contractor, once only |
| 25 | Retake Boarded Vessel at Contractor (DeepSeek, Grok) | **Confirmed** | gated Contractor, +300 |
| 26 | Tactical Strike Group Needed at Sr. Contractor (Muse, Claude) | Not confirmed | no rank gate in the data (chained mission); not in the guide |
| 27 | "Seek and Destroy Maulers (Super)" pays 2,004,000 (DeepSeek, Grok) | Not confirmed | no released mission with that name; Elite unlocks "Draw Out Maulers" and "Interdict Vanduul Maulers" |
| 28 | Recco "Welcome to the System" at Levski (Claude, Muse) | **Confirmed** | Nyx, +800 |
| 29 | Recco Prestige 1/2/3 give Drake Golem / MISC Prospector / ARGO MOLE Alliance (most) | **Confirmed** | reward items on the mission pages |
| 30 | Recco "Emergency" and "Idea for Isaac" are ranks (Gemini 01) | **Wrong** | they are story missions (+800 each) |
| 31 | Adagio intro "Salvage Introduction" (Claude) | **Wrong name** | it's "Adagio Holdings in Need of Salvagers" (+100); lawful salvage intro contracts cost 250-500 aUEC |
| 32 | Headhunters intro "Wanna be a Headhunter?" (Gemini) | **Confirmed** | Pyro, illegal, +50 |
| 33 | Vaughn "A Chance to Impress" (Muse, Gemini) | **Confirmed** | illegal; +100 standing, +500 Assassination |
| 34 | Dead Saints "Trial Cargo Haul" (Claude) | **Confirmed** | illegal, +50 Hauling |
| 35 | Wikelo intro "Wikelo Arrive to System" (Claude, Gemini 01) | **Confirmed** | +10 Wikelo rep; asks for Vestal Water and a Tundra Kopion Horn |
| 36 | "Where Wolf? Here Wolf" gives 30 Wikelo rep (Claude) | **Confirmed** | +30; costs 10 Wikelo Favors plus Vanduul parts |
| 37 | Most Special Wolf needs Very Good Customer (ChatGPT, Gemini) | Not confirmed | data shows a 5-Favor cost and a mission chain, no rank gate |
| 38 | CFP "Taking back from the Headhunters" needs Headhunters standing (Claude) | **Wrong** | gated on CFP's own standing (Sr. Contractor) |
| 39 | Vulture 2,513,700 aUEC at New Deal Lorville (Gemini) | **Confirmed** | UEX |
| 40 | Pitbull about 606,000 at Buy and Fly "Bloom or Terminus" (DeepSeek) | **Partly wrong** | 605,982 at Buy and Fly **Ruin Station, Checkmate, Orbituary** (UEX) |
| 41 | Earnings per hour figures (all) | Not confirmed | community estimates; not in the guide |
| 42 | 5.0 details (guild ranks, boards, multiplier) | Out of scope for v1 | PTU content; the guide covers live 4.10.3 |
| 43 | Ship Goals chapter: Avenger Titan 8 SCU / 1 seat; Cutlass Black 46 SCU, up to 3 crew, tractor beam; Freelancer MAX 120 SCU; Prospector 1 seat mining; MOLE up to 5 crew; C2 Hercules 696 SCU, 1-2 crew (added by Claude) | **Confirmed** | UEX `vehicles`; all six have live UEX purchase listings |

## How grind counts are computed

"About N contracts" = (rank threshold - reputation at the previous step) ÷
reputation per contract at that rank, rounded up, using the numbers above.
Actual counts vary with which contracts appear and with failures (failed or
abandoned contracts can cost reputation).
