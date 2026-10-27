# In-world HUD visual target (locked)

Reference: [inworld-hud-target.jpg](reference/inworld-hud-target.jpg) —
original Flash client, Nine Tails at level 7, autoplayed to the first NPC
quest (`【女兒國】紫霞`). This is the screen the HUD milestone must
resemble. It is a target, not a build order: data sources and asset
mapping come first, dialogs/menus/autoplay later.

## Element inventory (screen order)

| # | Element | Position | Data source | Status |
|---|---------|----------|-------------|--------|
| 1 | Player portrait frame + level badge, name `Tuan565…`, VIP badge, `儲值` button, `戰鬥力 424` banner | top-left | role info (`world.snapshot` has id/name/level/hp; combat power unevaluated) | art unmapped |
| 2 | Resource counters (coin/ingot, both 0 here) | top-left of portrait | unevaluated | art unmapped |
| 3 | Event banner with countdown + event icon row (`騎戰兵器`, `仙府爭霸`, `登陸獎勵(3)`, `七日聚`, `投資計劃`, `令牌`) | top-center | event system, unevaluated | deferred |
| 4 | Minimap (`南天門 (10,150)`, `1線`, clock, ring buttons) | top-right | position data + map tiles; clock/button behavior unevaluated | deferred |
| 5 | Quest tracker (`天宮之謎`, `整體進度 6%`) | right, under minimap | quest/task protocol exists server-side (`task_*` tables, `test_task`) | deferred |
| 6 | Player marker: green rune circle + nameplates (`散仙 九尾`, character name) | center | `world.snapshot` / `actor.moved` (live today) | marker exists, sprite art pending |
| 7 | NPC with nameplate (`【女兒國】紫霞`) | center-left | `actor.moved` kind=npc (live today) | rectangle marker only |
| 8 | Modal dialog (`購買藥品`, golden frame, `確認打開`) | center-right | popup system; shop protocol unevaluated | deferred (current `WindowManager` is placeholder text) |
| 9 | Chat (`綜合/私聊/陣伍/幫派/世界` tabs, `普通` filter, input, send) | bottom-left | chat protocol exists server-side (`test_chat`) | client view pending |
| 10 | HP/MP orb sphere + Q/W/E skill slots | bottom-left, above chat | vitals in snapshot (`hp/maxHp/mp/maxMp`) | art unmapped |
| 11 | Action bar 1–8 (slot 1 `近戰`) + menu row (`人物/包裹/技能/72變/任務/隊伍/好友/商城`) | bottom-center | menu modules land one by one; skills/bag/quests panels exist as stubs | art unmapped |
| 12 | Bottom green progress bar | very bottom | presumed exp, unevaluated | deferred |
| 13 | Autoplay to NPC quest at L7 | behavior | full quest/auto-pathing system | explicitly deferred, not milestone 1 |

## Recovered art pool (unmapped to regions)

`assets/ui/` already holds 766 recovered images plus contact sheets:
`gameui` (173), `hud-chat` (343), `shared-controls` (199),
`create-ui` (51). The next recovery task is the decoder-level pass that
maps these bitmaps to screen regions 1–11 above — the same
display-list work that was done for `create-ui` — not new extraction.

## Milestone order (proposal)

1. Deploy and lock onboarding (pending: docroot copies + commit).
2. Map recovered `gameui`/`shared-controls` bitmaps to HUD regions.
3. Player sprite visible and animated in-world, camera fixed (done).
4. HUD shell: portrait, orbs, action bar, chat wired to live snapshot data.
5. Dialogs, menus, minimap, events, autoplay — each its own milestone.
