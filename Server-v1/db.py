"""SQLite persistence for accounts, characters, sessions, and game state."""
import json
import math
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  pass_hash TEXT NOT NULL,
  created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS role_settings (
  role_id INTEGER PRIMARY KEY,
  quickbar_info TEXT,
  panel_config BLOB,
  ui_info BLOB,
  guaji_info BLOB,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Mirrors the legacy MySQL `role_stage` table (see docs/mysql-to-sqlite-migration.md).
-- Stage/stat/live-state columns live here instead of growing `characters`.
CREATE TABLE IF NOT EXISTS role_stage (
  role_id INTEGER PRIMARY KEY,
  map_id TEXT,
  map_x INTEGER,
  map_y INTEGER,
  line_no INTEGER DEFAULT 0,
  hp INTEGER,
  mp INTEGER,
  max_hp INTEGER,
  max_mp INTEGER,
  buff TEXT,
  props TEXT,
  state INTEGER DEFAULT 0,
  map_node TEXT,
  ti_li INTEGER DEFAULT 0,
  shanbi_val INTEGER DEFAULT 0,
  pk_info TEXT,
  meiren_info TEXT,
  zuoqi_info TEXT,
  copy_info TEXT,
  free_fly_count INTEGER DEFAULT 0,
  fly_count_refresh_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_skill (
  role_id INTEGER NOT NULL,
  skill_key TEXT NOT NULL,
  category TEXT NOT NULL,
  level INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, skill_key),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_shenjiang (
  role_id INTEGER NOT NULL,
  shenjiang_key TEXT NOT NULL,
  shenjiang_id TEXT NOT NULL,
  jiangxing_id TEXT,
  jiangxing_rank INTEGER DEFAULT 1,
  skills TEXT,
  jiangxing_state INTEGER DEFAULT 0,
  cur_jiangxing_id TEXT,
  fail_count INTEGER DEFAULT 0,
  rank_fail_count INTEGER DEFAULT 0,
  rank_lucky INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, shenjiang_key),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_chengjiu (
  role_id INTEGER NOT NULL,
  task_id TEXT NOT NULL,
  task_status INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, task_id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_equip (
  role_id INTEGER NOT NULL,
  slot_num INTEGER NOT NULL,
  goods_id TEXT NOT NULL,
  rare_level INTEGER DEFAULT 0,
  item_level INTEGER DEFAULT 0,
  attributes TEXT,
  PRIMARY KEY(role_id, slot_num),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_attr_buff (
  role_id INTEGER NOT NULL,
  attribute_id TEXT NOT NULL,
  count INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, attribute_id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_vip (
  role_id INTEGER PRIMARY KEY,
  vip_level INTEGER DEFAULT 0,
  state_day INTEGER DEFAULT 0,
  state_week INTEGER DEFAULT 0,
  state_tejia TEXT,
  prop_value INTEGER DEFAULT 0,
  tody_prop_value INTEGER DEFAULT 0,
  prop_use_time INTEGER DEFAULT 0,
  day_time INTEGER DEFAULT 0,
  week_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Kaifu lottery state per role (legacy RoleVipKaifu subset: the claimed
-- id map plus the used lottery count; the row is ensured on first read
-- like RoleVipKaifuDao use in roleLogin). -- QQ-member binding per role (legacy role_qq_list subset: qq, author and
 -- the reward-claimed mark written by VipQqServiceImpl.vipQqOK/getRewards).
 CREATE TABLE IF NOT EXISTS role_qq_list (
   role_id INTEGER PRIMARY KEY,
   qq TEXT,
   user_name TEXT,
   is_get_rewards INTEGER DEFAULT 0,
   FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
 );
 -- QQ-member config (legacy vip_qq: admin-set threshold, image and
 -- service QQ; the first row is the active config like DataContainer's).
 CREATE TABLE IF NOT EXISTS vip_qq (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   min_recharge INTEGER DEFAULT 0,
   pic TEXT,
   qq TEXT
 );
 CREATE TABLE IF NOT EXISTS role_vip_kaifu (
  role_id INTEGER PRIMARY KEY,
  lingqu_reward TEXT DEFAULT '{}',
  lotter_reward INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Appraisal state per role (no legacy source table; local-only like
-- role_settings): jianding count/time/exp plus the hecheng count that
-- 34006 reports alongside the exp.
CREATE TABLE IF NOT EXISTS role_jianding (
  role_id INTEGER PRIMARY KEY,
  jianding_count INTEGER DEFAULT 0,
  jianding_time INTEGER DEFAULT 0,
  jianding_exp INTEGER DEFAULT 0,
  hecheng_count INTEGER DEFAULT 0,
  hecheng_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Xianjie/chenghao id arrays for a role (legacy role_xianjiechenhao
-- subset: the JSON id lists the title bags resolve through).
CREATE TABLE IF NOT EXISTS role_xianjiechenhao (
  role_id INTEGER PRIMARY KEY,
  xianjie_id TEXT,
  chenhao_id TEXT,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Mount rank per role (legacy role_zuoqi subset: rank gates the ZUOQI bag
-- via ZuoQiWrapper, cur_rank is the ridden rank, lucky_value the jinjie
-- blessing, update_time the ms timestamp timerTask resets against,
-- fail_count/total_exp the jinjie pity counters, free_jb the free-upgrade
-- flag, lucky_goods_id/expire/add_lucky the blessing-pill state, and
-- kaifu_data the fastjson blob (cost-count map, fanhuan/meiren flags);
-- attribute_goods_id is NULL for every migrated role so it is not copied).
CREATE TABLE IF NOT EXISTS role_zuoqi (
  role_id INTEGER PRIMARY KEY,
  zuoqi_rank INTEGER DEFAULT 0,
  zuoqi_cur_rank INTEGER DEFAULT 0,
  lucky_value INTEGER DEFAULT 0,
  update_time INTEGER DEFAULT 0,
  fail_count INTEGER DEFAULT 0,
  total_exp INTEGER DEFAULT 0,
  free_jb INTEGER DEFAULT 0,
  lucky_goods_id TEXT,
  lucky_goods_expire_time INTEGER DEFAULT 0,
  add_lucky_value INTEGER DEFAULT 0,
  kaifu_data TEXT,
  attribute_goods_id TEXT,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Pets per role (legacy role_pet subset: pet_lv/pet_rank feed 136000's
-- [petId, lv, rank, lvExp, rankExp] rows; rank pity columns ride along
-- for the later upgrade/jinjie slice; live MySQL carries no rows).
CREATE TABLE IF NOT EXISTS role_pet (
  id TEXT PRIMARY KEY,
  role_id INTEGER NOT NULL,
  pet_id TEXT,
  pet_lv INTEGER DEFAULT 0,
  pet_lv_exp INTEGER DEFAULT 0,
  pet_rank INTEGER DEFAULT 0,
  pet_rank_exp INTEGER DEFAULT 0,
  pet_rank_fail INTEGER DEFAULT 0,
  pet_rank_update_time INTEGER DEFAULT 0,
  create_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Pet formation per role (legacy role_pet_zhenfa subset: zhenfa_id and
-- upgrade_exp plus the zhenfa_pet fastjson {pos: petId} map feed 136000's
-- [zhenfaId, upgradeExp, [[pos, petId]...]] slot; chuzhan/upgrade-count
-- the remaining slots; jinjie columns ride along for the later slice).
CREATE TABLE IF NOT EXISTS role_pet_zhenfa (
  role_id INTEGER PRIMARY KEY,
  zhenfa_id TEXT,
  pet_chuzhan_id TEXT,
  upgrade_exp INTEGER DEFAULT 0,
  jinjie_fail_count INTEGER DEFAULT 0,
  jinjie_time INTEGER DEFAULT 0,
  jinjie_data TEXT,
  zhenfa_pet TEXT DEFAULT '{}',
  pet_upgrade_count INTEGER DEFAULT 0,
  pet_upgrade_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Mount-upgrade refund feed (ZuoqiFanhuanDaoImpl filedb 'zuoqi/fanhuan':
-- every claim appends [roleName, count]; loadNearestInfos returns the whole
-- list, null when the file is absent, i.e. no rows here).
CREATE TABLE IF NOT EXISTS zuoqi_fanhuan (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role_name TEXT NOT NULL,
  goods_count INTEGER DEFAULT 0
);
-- Login gift-pack claim per role (legacy role_loginlibao subset:
-- lingqujson is the fastjson {id: state} map, lingqu_time the last claim ms).
CREATE TABLE IF NOT EXISTS role_loginlibao (
  role_id INTEGER PRIMARY KEY,
  lingqujson TEXT,
  lingqu_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Level gift-pack claim per role (legacy role_lvlibao subset: state is the
-- fastjson {number: 0/1} map LynquLvLiBao reads).
CREATE TABLE IF NOT EXISTS role_lvlibao (
  role_id INTEGER PRIMARY KEY,
  state TEXT DEFAULT '{}',
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- In-game mail (role_email subset + system broadcast table). Fresh roles
-- have no rows, so 63001 answers null like Java's empty-list branch.
CREATE TABLE IF NOT EXISTS system_email (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT DEFAULT '',
  content TEXT DEFAULT '',
  attachment TEXT DEFAULT '',
  created INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS role_email (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role_id INTEGER NOT NULL,
  system_email_id INTEGER DEFAULT 0,
  title TEXT DEFAULT '',
  content TEXT DEFAULT '',
  attachment TEXT DEFAULT '',
  jb INTEGER DEFAULT 0,
  yb INTEGER DEFAULT 0,
  is_read INTEGER DEFAULT 0,
  is_claimed INTEGER DEFAULT 0,
  created INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Consecutive-login reward state (RoleLoginlingjiang subset: the streak day
-- count plus the fastjson {day: 1} claim map).
CREATE TABLE IF NOT EXISTS role_loginlingjiang (
  role_id INTEGER PRIMARY KEY,
  day_number INTEGER DEFAULT 1,
  lingqujson TEXT DEFAULT '{}',
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Titles (RoleTouxian subset: worn title id + JSON owned-id list).
CREATE TABLE IF NOT EXISTS role_touxian (
  role_id INTEGER PRIMARY KEY,
  peidai_id TEXT,
  jihuoids TEXT DEFAULT '[]',
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Wings (RoleGuangyi subset: worn id, upgrade level, blessing, wear flag
-- and the attribute-dan JSON map guangyiInfo reports).
CREATE TABLE IF NOT EXISTS role_guangyi (
  role_id INTEGER PRIMARY KEY,
  peidai_id INTEGER DEFAULT 0,
  level INTEGER DEFAULT 1,
  lucky INTEGER DEFAULT 0,
  ispeidai INTEGER DEFAULT 0,
  attr_dan TEXT DEFAULT '{}',
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Qibing progression (RoleQizhanbinqi subset: binqi_level is the ridden
-- level, fail_count/lucky_value the upgrade pity, upgrade_time the last
-- success, lingqu_time the trial grant for the level-1 guoqi window,
-- update_time the ms stamp clear() resets the pity against, and
-- attribute_dan the {danId: count} JSON map; log_update_time is a log
-- column with no wire effect, so it is not copied). Stored under the
-- role id like the zuoqi row (Java keys userRoleId, the same id).
CREATE TABLE IF NOT EXISTS role_qizhanbinqi (
  role_id INTEGER PRIMARY KEY,
  binqi_level INTEGER DEFAULT 0,
  fail_count INTEGER DEFAULT 0,
  lucky_value INTEGER DEFAULT 0,
  upgrade_time INTEGER DEFAULT 0,
  lingqu_time INTEGER DEFAULT 0,
  update_time INTEGER DEFAULT 0,
  attribute_dan TEXT,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Immortal-worship counts (RoleBaiXian.baiXianInfo subset: JSON {god: n}
-- plus the last worship day; todayChuli resets daily like Java).
CREATE TABLE IF NOT EXISTS role_baixian (
  role_id INTEGER PRIMARY KEY,
  counts TEXT DEFAULT '{}',
  last_day TEXT DEFAULT '',
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Story-dungeon progress (RoleJuqingfuben subset: highest cleared chapter,
-- daily clear counts, sweep state, best times, pending awards, progress).
CREATE TABLE IF NOT EXISTS role_juqingfuben (
  role_id INTEGER PRIMARY KEY,
  passed_highest_id INTEGER,
  passed_ids_daily TEXT,
  auto_pass_info TEXT,
  best_passed_info TEXT,
  refresh_time INTEGER,
  award_info TEXT,
  tiaozhan_jindu TEXT,
  pending_award TEXT,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Clan-dungeon progress (RoleZuwufuben: highest cleared dungeon, daily
-- remaining attempts, bought attempts, sweep state, daily touch).
CREATE TABLE IF NOT EXISTS role_zuwufuben (
  role_id INTEGER PRIMARY KEY,
  pass_max_id INTEGER,
  everyday_pass_data TEXT,
  everyday_time INTEGER,
  buy_count_data TEXT,
  saodang_data TEXT,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Activated clan guardians (RoleZuwu subset: guardian id, level, exp,
-- jieshu tier, fail count; jihuoZuwu creates level-1 rows on first clear).
CREATE TABLE IF NOT EXISTS role_zuwu (
  role_id INTEGER NOT NULL,
  zuwu_id TEXT NOT NULL,
  level INTEGER DEFAULT 1,
  exp INTEGER DEFAULT 0,
  jieshu INTEGER DEFAULT 0,
  fail_count INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, zuwu_id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Kapai reward states (per-entry [got, canClaim] markers backing 121001;
-- card counts themselves live in role_bag_dummy like Java's getCount).
CREATE TABLE IF NOT EXISTS role_kapai (
  role_id INTEGER PRIMARY KEY,
  state TEXT DEFAULT '{}',
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Dafuwong board state (RoleDafuwong: slot, grade, zanshi counters plus
-- the roll counters and last-roll stamp clear() resets daily/weekly).
CREATE TABLE IF NOT EXISTS role_dafuwong (
  role_id INTEGER PRIMARY KEY,
  slot INTEGER DEFAULT 0,
  grade INTEGER DEFAULT 0,
  zanshi INTEGER DEFAULT 0,
  roll_count INTEGER DEFAULT 0,
  tongqian_count INTEGER DEFAULT 0,
  last_roll_ms INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Timed-shop purchases (RoleXianshibuy: JSON {id: [count, lastMs, cdMs]}
-- plus the day the map was last reset; XianshiBuy keeps the server-wide
-- {id: sold} counts in one row).
CREATE TABLE IF NOT EXISTS role_xianshibuy (
  role_id INTEGER PRIMARY KEY,
  buy_data TEXT DEFAULT '{}',
  buy_day TEXT DEFAULT '',
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS xianshi_buy (
  id TEXT PRIMARY KEY,
  buy_data TEXT DEFAULT '{}'
);
-- Micro-client login-device reward (RoleDengluqi: claim state plus the day
-- stamp initDengLuQi resets on; 10060 reads the state, 10061 claims it).
CREATE TABLE IF NOT EXISTS role_jiangli_list (
  role_id INTEGER PRIMARY KEY,
  baidu_yingyin INTEGER DEFAULT 0,
  baidu_yingyin_xiazai INTEGER DEFAULT 0,
  baidu_yingyin_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS role_dengluqi (
  role_id INTEGER PRIMARY KEY,
  lingqu_state INTEGER DEFAULT 0,
  lingqu_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Online-time rewards (RoleOnlineReward: daily/monthly counters in ms,
-- comma-joined claimed tier ids, bind-yb accrual and the session anchor
-- role_online_time that read-time totals are measured from).
CREATE TABLE IF NOT EXISTS role_online_reward (
  role_id INTEGER PRIMARY KEY,
  month INTEGER,
  online_time INTEGER DEFAULT 0,
  month_online_time INTEGER DEFAULT 0,
  refresh_time INTEGER,
  online_reward TEXT DEFAULT '',
  is_lingqu_reward INTEGER DEFAULT 0,
  month_bind_yb INTEGER DEFAULT 0,
  role_online_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Escort state per role (RoleHusong subset: the beauty id, daily escort
-- count with its day stamp, and the rob count with its stamp; 83001 reads
-- the remainder, 83008 the rob remainder).
CREATE TABLE IF NOT EXISTS role_husong (
  role_id INTEGER PRIMARY KEY,
  mei_qi_id TEXT,
  husong_times INTEGER DEFAULT 0,
  refresh_time INTEGER,
  dajie_cishu INTEGER DEFAULT 0,
  dajie_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Resource-recovery claims (RoleZyzhuihui subset: JSON {id: claimed}).
CREATE TABLE IF NOT EXISTS role_zhuihui (
  role_id INTEGER PRIMARY KEY,
  state TEXT DEFAULT '{}',
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Owned meiren per role (legacy role_meiren subset: the id/level/heti
-- triple replaceMeirenAttribute resolves through meiren.jat).
CREATE TABLE IF NOT EXISTS role_meiren (
  role_id INTEGER NOT NULL,
  meiren_id TEXT NOT NULL,
  meiren_level INTEGER DEFAULT 0,
  meiren_heti INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, meiren_id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Socketed-gem rows per role (legacy role_baoshi subset: one row per
-- socketed grid; level/exp/fail_count drive jihuo/upgrade).
CREATE TABLE IF NOT EXISTS role_baoshi (
  role_id INTEGER NOT NULL,
  id TEXT NOT NULL,
  part INTEGER DEFAULT 0,
  grid INTEGER DEFAULT 0,
  level INTEGER DEFAULT 0,
  fail_count INTEGER DEFAULT 0,
  exp INTEGER DEFAULT 0,
  update_time INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Bag slots per role (legacy role_bag_slot subset: slot rows 1..150 are the
-- bag, 151+ the storage; attributes holds the GoodsEquipVo/ExpVo JSON).
CREATE TABLE IF NOT EXISTS role_bag_slot (
  role_id INTEGER NOT NULL,
  slot_num INTEGER NOT NULL,
  bag_id TEXT,
  goods_id TEXT NOT NULL,
  count INTEGER DEFAULT 0,
  bind INTEGER DEFAULT 0,
  expire_time INTEGER,
  rare_level INTEGER DEFAULT 0,
  item_level INTEGER DEFAULT 0,
  attributes TEXT,
  PRIMARY KEY(role_id, slot_num),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Skillbook equip slots per role (legacy role_skillbook_slot subset: the
-- 10001..10056 worn books; same StoreGoods columns as role_bag_slot).
CREATE TABLE IF NOT EXISTS role_skillbook_slot (
  role_id INTEGER NOT NULL,
  slot_num INTEGER NOT NULL,
  bag_id TEXT,
  goods_id TEXT NOT NULL,
  count INTEGER DEFAULT 0,
  bind INTEGER DEFAULT 0,
  expire_time INTEGER,
  rare_level INTEGER DEFAULT 0,
  item_level INTEGER DEFAULT 0,
  attributes TEXT,
  PRIMARY KEY(role_id, slot_num),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Sold-item buyback per role (legacy role_bag_buyback subset: the id is the
-- sold bag row's guid, slot_num its origin slot; createtime orders eviction).
CREATE TABLE IF NOT EXISTS role_bag_buyback (
  role_id INTEGER NOT NULL,
  buyback_id TEXT NOT NULL,
  slot_num INTEGER,
  goods_id TEXT NOT NULL,
  count INTEGER DEFAULT 0,
  bind INTEGER DEFAULT 0,
  expire_time INTEGER,
  rare_level INTEGER DEFAULT 0,
  item_level INTEGER DEFAULT 0,
  attributes TEXT,
  createtime INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, buyback_id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Special-type prop use counts per role (legacy role_prop subset: daily
-- useCount per goods id feeds the 30307 count query).
CREATE TABLE IF NOT EXISTS role_prop (
  role_id INTEGER NOT NULL,
  goods_id TEXT NOT NULL,
  use_start_time INTEGER,
  use_stop_time INTEGER,
  surplus_value INTEGER,
  surplus_time INTEGER,
  use_count INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, goods_id),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Sign-in state per role (legacy role_qiandao subset: the counters and the
-- comma-joined day/reward lists that 58011 formats).
CREATE TABLE IF NOT EXISTS role_qiandao (
  role_id INTEGER PRIMARY KEY,
  total_qiandao_count INTEGER DEFAULT 0,
  month INTEGER,
  month_qiandao TEXT,
  total_qiandao_reward TEXT,
  month_qiandao_reward TEXT,
  week INTEGER,
  vip_buqian_count INTEGER DEFAULT 0,
  qiandao_time INTEGER,
  online_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Vip event state per role (legacy role_vip_huodong subset: the fixed
-- reward and lottery marks keyed by vip tier).
CREATE TABLE IF NOT EXISTS role_vip_huodong (
  role_id INTEGER NOT NULL,
  vip INTEGER NOT NULL,
  choujiang_state INTEGER DEFAULT 0,
  lingqu_state INTEGER DEFAULT 0,
  PRIMARY KEY(role_id, vip),
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Running main quest per role (legacy task_main subset: current task, state,
-- kill-condition string, receive/create times; one row per role).
CREATE TABLE IF NOT EXISTS task_main (
  role_id INTEGER PRIMARY KEY,
  task_uid TEXT,
  task_id TEXT,
  state INTEGER DEFAULT 0,
  condition TEXT,
  recevie_time INTEGER,
  create_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Taofa quests per role (legacy TaskTaofa: one row per received quest; the
-- id is the legacy row guid, ts_* carry the merged swallow rewards).
CREATE TABLE IF NOT EXISTS task_taofa (
  id TEXT PRIMARY KEY,
  role_id INTEGER NOT NULL,
  task_id TEXT,
  master_count INTEGER DEFAULT 0,
  task_state INTEGER DEFAULT 0,
  ts_state INTEGER DEFAULT 0,
  ts_reward_jb INTEGER DEFAULT 0,
  ts_reward_exp INTEGER DEFAULT 0,
  ts_reward_zhenqi INTEGER DEFAULT 0,
  ts_reward_bing_yb INTEGER DEFAULT 0,
  ts_reward_prestige INTEGER DEFAULT 0,
  update_time INTEGER,
  create_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Daily taofa counters per role (legacy TaskTaofaState: tunshi, use
-- (hebing), finish and total counts plus the day-stamp create_time).
CREATE TABLE IF NOT EXISTS task_taofa_state (
  role_id INTEGER PRIMARY KEY,
  tunshi_count INTEGER DEFAULT 0,
  hebing_count INTEGER DEFAULT 0,
  finish_count INTEGER DEFAULT 0,
  total_count INTEGER DEFAULT 0,
  create_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Daily richang quest per role (legacy TaskRichang: condition/reward/loop
-- config ids, kill-condition string, loop, state, fufei and receive times;
-- one quest per role, so role_id is the key and id is the quest guid).
CREATE TABLE IF NOT EXISTS task_richang (
  role_id INTEGER PRIMARY KEY,
  id TEXT,
  condition_config_id TEXT,
  reward_config_id TEXT,
  reward_loop_config_id TEXT,
  task_condition TEXT,
  current_loop INTEGER DEFAULT 1,
  task_state INTEGER DEFAULT 0,
  fufei_state INTEGER DEFAULT 0,
  recevie_time INTEGER,
  create_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Guild-task quest per role (legacy RoleGonghuiTask: same one-quest-per-role
-- shape as task_richang; the guild gate lives in guild_member, since the
-- full GuildAction family is unported).
CREATE TABLE IF NOT EXISTS task_gonghui (
  role_id INTEGER PRIMARY KEY,
  id TEXT,
  condition_config_id TEXT,
  reward_config_id TEXT,
  reward_loop_config_id TEXT,
  task_condition TEXT,
  current_loop INTEGER DEFAULT 1,
  task_state INTEGER DEFAULT 0,
  fufei_state INTEGER DEFAULT 0,
  recevie_time INTEGER,
  create_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Battle-formation progress per role (legacy RolePozhen: one row per role;
-- locations is the 'main-idx;...' megre map, max_location the 'main-idx'
-- splitPZ cursor, *_time columns are epoch millis, award fields back the
-- useAwardProp reward buff).
CREATE TABLE IF NOT EXISTS role_pozhen (
  role_id INTEGER PRIMARY KEY,
  max_location TEXT,
  locations TEXT,
  can_use_count INTEGER DEFAULT 0,
  buy_count INTEGER DEFAULT 0,
  refresh_count INTEGER DEFAULT 0,
  in_mopup INTEGER DEFAULT 0,
  sd_main_id INTEGER DEFAULT 0,
  mopup_time INTEGER DEFAULT 0,
  recovery_time INTEGER DEFAULT 0,
  refresh_time INTEGER DEFAULT 0,
  award_rate REAL,
  expire_time INTEGER,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Online-gift state per role (legacy RoleHuodong.max_count JSON map;
-- the online_gift {day, id, logintime, minute[, end]} object rides under
-- the 'online_gift' key, like the jar's getValue/setValue helpers.
-- Sibling activity columns land here only when a batch that needs them
-- does; nothing else reads this table yet.)
CREATE TABLE IF NOT EXISTS role_huodong (
  role_id INTEGER PRIMARY KEY,
  max_count TEXT DEFAULT '',
  day_count TEXT DEFAULT '',
  mall_buy_count TEXT DEFAULT '',
  pay_yb TEXT DEFAULT '',
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Global per-activity mall sell counts (legacy HuodongInfo subset: the
-- mallSellInfo JSON maps goodsId to units sold, keyed by activity id.
-- Only the 70550 buy batch reads and writes it.)
CREATE TABLE IF NOT EXISTS huodong_info (
  huodong_id TEXT PRIMARY KEY,
  mall_sell_info TEXT DEFAULT ''
);
-- Recharge records (legacy recharge_record subset: one row per payment
-- or GM/goods-exchange grant; money_num is the granted YB count,
-- money_type 2 is YB, recharge_type 1/2 counts toward activity totals
-- (3/4 are excluded), recharge_state is '0' granted, '1' pending grant,
-- '9' revoked, '1001'/'1003'/'1004'/'1005' failed. The jar compares the
-- state as text, so '0'/'1' match `<= '1'` while '9' and the 100x codes
-- do not. create_time is ms epoch like every other port timestamp.)
CREATE TABLE IF NOT EXISTS recharge_record (
  id TEXT PRIMARY KEY,
  user_role_id TEXT NOT NULL,
  rmb REAL DEFAULT 0,
  money_type INTEGER DEFAULT 2,
  money_num INTEGER DEFAULT 0,
  is_calc INTEGER DEFAULT 0,
  recharge_type TEXT DEFAULT '1',
  platform_type TEXT DEFAULT '',
  recharge_state TEXT DEFAULT '1',
  order_id TEXT DEFAULT '',
  create_time INTEGER DEFAULT 0,
  server_id TEXT DEFAULT '',
  user_guid TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_recharge_record_role ON recharge_record(user_role_id);
CREATE INDEX IF NOT EXISTS idx_recharge_record_order ON recharge_record(order_id);
-- Guild system (Guild/Member/Gongxian/Info entities: guilds hold the
-- banner/level/funds/message/setting/master columns, members the
-- position (0 master, 1 vice, 2 admin, 3 member) and contribution
-- totals, applies the pending join requests, gongxian the per-guild
-- contribution ledger, info the guild event log).
CREATE TABLE IF NOT EXISTS guild (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  banner_id INTEGER DEFAULT 0,
  banner_level INTEGER DEFAULT 1,
  banner_name TEXT DEFAULT '',
  user_role_id TEXT DEFAULT '',
  vice_user_role_id TEXT DEFAULT '',
  guild_message TEXT DEFAULT '',
  active_value INTEGER DEFAULT 0,
  warn_value INTEGER DEFAULT 0,
  guild_setting INTEGER DEFAULT 0,
  money INTEGER DEFAULT 0,
  qinglong_count INTEGER DEFAULT 0,
  baihu_count INTEGER DEFAULT 0,
  zhuque_count INTEGER DEFAULT 0,
  xuanwu_count INTEGER DEFAULT 0,
  fighting INTEGER DEFAULT 0,
  create_time INTEGER DEFAULT 0,
  update_time INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS guild_member (
  role_id INTEGER PRIMARY KEY,
  guild_id TEXT NOT NULL,
  position INTEGER DEFAULT 3,
  gongxian INTEGER DEFAULT 0,
  gongxian_sum INTEGER DEFAULT 0,
  create_time INTEGER DEFAULT 0,
  update_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS guild_apply (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  role_id INTEGER NOT NULL,
  create_time INTEGER DEFAULT 0,
  UNIQUE(guild_id, role_id)
);
CREATE TABLE IF NOT EXISTS guild_gongxian (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  role_id INTEGER NOT NULL,
  money INTEGER DEFAULT 0,
  qinglong_count INTEGER DEFAULT 0,
  baihu_count INTEGER DEFAULT 0,
  zhuque_count INTEGER DEFAULT 0,
  xuanwu_count INTEGER DEFAULT 0,
  create_time INTEGER DEFAULT 0,
  update_time INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS guild_info (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  msg TEXT DEFAULT '',
  create_time INTEGER DEFAULT 0
);
-- Bag dummy goods per role (legacy role_bag_dummy: goods a bagdummy query
-- lists back to the client; the id is the legacy row guid).
CREATE TABLE IF NOT EXISTS role_bag_dummy (
  id TEXT PRIMARY KEY,
  role_id INTEGER NOT NULL,
  goods_id TEXT NOT NULL,
  goods_count INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
-- Player stalls (Booth entity subset: name/state plus the collected-money
-- balances boothJb/boothYb; boothBuyTime gates the trade-exp award).
CREATE TABLE IF NOT EXISTS booth (
  role_id TEXT PRIMARY KEY,
  booth_name TEXT,
  booth_state INTEGER DEFAULT 1,
  booth_jb INTEGER DEFAULT 0,
  booth_yb INTEGER DEFAULT 0,
  booth_buy_time INTEGER,
  created INTEGER DEFAULT 0
);
-- Stall listings (BoothSell subset: goods rows at slots 0..10 plus the
-- money-market rows at slots 11 (YB offered) and 12 (YXB offered)).
CREATE TABLE IF NOT EXISTS booth_sell (
  id TEXT PRIMARY KEY,
  role_id TEXT NOT NULL,
  goods_id TEXT,
  count INTEGER DEFAULT 0,
  slot INTEGER DEFAULT 0,
  item_level INTEGER DEFAULT 0,
  rare_level INTEGER DEFAULT 0,
  attributes TEXT,
  expire_time INTEGER,
  sell_jb INTEGER DEFAULT 0,
  sell_yb INTEGER DEFAULT 0,
  bind INTEGER DEFAULT 0,
  created INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_booth_sell_role ON booth_sell(role_id);
-- Stall trade log (BoothTradeLog subset: seller-view logCode rows, newest
-- first, capped at 50 per seller like insertBoothTradeLog).
CREATE TABLE IF NOT EXISTS booth_trade_log (
  id TEXT PRIMARY KEY,
  role_id TEXT NOT NULL,
  log_type INTEGER DEFAULT 0,
  log_code TEXT,
  created INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_booth_trade_log_role ON booth_trade_log(role_id);
-- Friend lists (one-sided directed rows: owner adds target, no reciprocal
-- row; foe rows carry the kill counter, capped at +/-999 like Java).
CREATE TABLE IF NOT EXISTS role_friend (
  id TEXT PRIMARY KEY,
  user_role_id TEXT NOT NULL,
  friend_id TEXT NOT NULL,
  order_id INTEGER DEFAULT 0,
  created INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_role_friend_owner ON role_friend(user_role_id);
CREATE INDEX IF NOT EXISTS idx_role_friend_target ON role_friend(friend_id);
CREATE TABLE IF NOT EXISTS role_foe (
  id TEXT PRIMARY KEY,
  user_role_id TEXT NOT NULL,
  foe_id TEXT NOT NULL,
  foe_count INTEGER DEFAULT 0,
  order_id INTEGER DEFAULT 0,
  created INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_role_foe_owner ON role_foe(user_role_id);
CREATE INDEX IF NOT EXISTS idx_role_foe_target ON role_foe(foe_id);
CREATE TABLE IF NOT EXISTS role_blacklist (
  id TEXT PRIMARY KEY,
  user_role_id TEXT NOT NULL,
  blacklist_id TEXT NOT NULL,
  created INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_role_blacklist_owner ON role_blacklist(user_role_id);
CREATE INDEX IF NOT EXISTS idx_role_blacklist_target ON role_blacklist(blacklist_id);
CREATE TABLE IF NOT EXISTS role_contacts (
  id TEXT PRIMARY KEY,
  user_role_id TEXT NOT NULL,
  contacts_id TEXT NOT NULL,
  created INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_role_contacts_owner ON role_contacts(user_role_id);
CREATE INDEX IF NOT EXISTS idx_role_contacts_target ON role_contacts(contacts_id);
-- Friend headline (xinqing mood text, friendCount of added friends).
CREATE TABLE IF NOT EXISTS friend_info (
  user_role_id TEXT PRIMARY KEY,
  xinqing TEXT,
  friend_count INTEGER DEFAULT 0
);
-- Bag unlock state per role (legacy role_bag_state subset: capacities gate
-- the 30000 lock VOs; *_slot_time feeds the unlock countdown).
CREATE TABLE IF NOT EXISTS role_bag_state (
  role_id INTEGER PRIMARY KEY,
  bag_capacity INTEGER DEFAULT 0,
  bag_slot_time INTEGER DEFAULT 0,
  bag_update_slot_time INTEGER DEFAULT 0,
  storage_capacity INTEGER DEFAULT 0,
  storage_slot_time INTEGER DEFAULT 0,
  storage_update_slot_time INTEGER DEFAULT 0,
  FOREIGN KEY(role_id) REFERENCES characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS characters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  legacy_id TEXT,
  account TEXT NOT NULL,
  server_id TEXT NOT NULL,
  name TEXT NOT NULL,
  job TEXT NOT NULL DEFAULT 'A',
  sex INTEGER NOT NULL DEFAULT 0,
  face TEXT DEFAULT '',
  level INTEGER NOT NULL DEFAULT 1,
  exp INTEGER,
  map_id TEXT,
  map_x INTEGER,
  map_y INTEGER,
  hp INTEGER,
  mp INTEGER,
  max_hp INTEGER,
  max_mp INTEGER,
  tongqian INTEGER,
  bind_lingshi INTEGER,
  lingshi INTEGER,
  recive_yb INTEGER,
  zhenqi INTEGER,
  shengwang INTEGER,
  created INTEGER NOT NULL,
  UNIQUE(account, server_id, name)
);
'''

# Columns that may be added to an existing characters table.
CHARACTER_COLUMNS = {
    'legacy_id': 'TEXT',
    'level': 'INTEGER NOT NULL DEFAULT 1',
    'exp': 'INTEGER',
    'map_id': 'TEXT',
    'map_x': 'INTEGER',
    'map_y': 'INTEGER',
    'hp': 'INTEGER',
    'mp': 'INTEGER',
    'max_hp': 'INTEGER',
    'max_mp': 'INTEGER',
    'tongqian': 'INTEGER',
    'bind_lingshi': 'INTEGER',
    'lingshi': 'INTEGER',
    'recive_yb': 'INTEGER',
    # user_role.zhenqi/shengwang (UserRole entity; the migrator already reads
    # both but only stored them once these columns existed).
    'zhenqi': 'INTEGER',
    'shengwang': 'INTEGER',
}

# role_stage columns accepted by save_role_stage (legacy MySQL names).
STAGE_COLUMNS = {
    'map_id': 'TEXT',
    'map_x': 'INTEGER',
    'map_y': 'INTEGER',
    'line_no': 'INTEGER',
    'hp': 'INTEGER',
    'mp': 'INTEGER',
    'max_hp': 'INTEGER',
    'max_mp': 'INTEGER',
    'buff': 'TEXT',
    'props': 'TEXT',
    'state': 'INTEGER',
    'map_node': 'TEXT',
    'ti_li': 'INTEGER',
    'shanbi_val': 'INTEGER',
    'pk_info': 'TEXT',
    'meiren_info': 'TEXT',
    'zuoqi_info': 'TEXT',
    'copy_info': 'TEXT',
    'free_fly_count': 'INTEGER',
    'fly_count_refresh_time': 'INTEGER',
}


def _local_day_start_ms(now_ms):
    """Local-midnight epoch ms for the day containing now_ms."""
    try:
        secs = int(now_ms) // 1000
    except (TypeError, ValueError):
        secs = 0
    loc = time.localtime(secs)
    return int(time.mktime((loc.tm_year, loc.tm_mon, loc.tm_mday,
                            0, 0, 0, 0, 0, -1)) * 1000)


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            present = {row['name'] for row in self.db.execute(
                'PRAGMA table_info(characters)')}
            for name, declaration in CHARACTER_COLUMNS.items():
                if name not in present:
                    self.db.execute(
                        f'ALTER TABLE characters ADD COLUMN {name} {declaration}')
            vip_cols = {row['name'] for row in self.db.execute(
                'PRAGMA table_info(role_vip)')}
            if 'prop_use_time' not in vip_cols:
                self.db.execute(
                    'ALTER TABLE role_vip ADD COLUMN prop_use_time INTEGER DEFAULT 0')
            email_cols = {row['name'] for row in self.db.execute(
                'PRAGMA table_info(role_email)')}
            for column in ('jb', 'yb'):
                if column not in email_cols:
                    self.db.execute(
                        f'ALTER TABLE role_email ADD COLUMN {column}'
                        ' INTEGER DEFAULT 0')
            huodong_cols = {row['name'] for row in self.db.execute(
                'PRAGMA table_info(role_huodong)')}
            for column in ('day_count', 'mall_buy_count', 'pay_yb'):
                if column not in huodong_cols:
                    self.db.execute(
                        f'ALTER TABLE role_huodong ADD COLUMN {column} TEXT')
            juqing_cols = {row['name'] for row in self.db.execute(
                'PRAGMA table_info(role_juqingfuben)')}
            if 'pending_award' not in juqing_cols:
                self.db.execute(
                    'ALTER TABLE role_juqingfuben'
                    ' ADD COLUMN pending_award TEXT')
            member_cols = {row['name'] for row in self.db.execute(
                'PRAGMA table_info(guild_member)')}
            for column, declaration in (
                    ('position', 'INTEGER DEFAULT 3'),
                    ('gongxian_sum', 'INTEGER DEFAULT 0'),
                    ('create_time', 'INTEGER DEFAULT 0'),
                    ('update_time', 'INTEGER DEFAULT 0')):
                if column not in member_cols:
                    self.db.execute(
                        f'ALTER TABLE guild_member ADD COLUMN {column}'
                        f' {declaration}')
            zuoqi_cols = {row['name'] for row in self.db.execute(
                'PRAGMA table_info(role_zuoqi)')}
            if 'lucky_value' not in zuoqi_cols:
                self.db.execute(
                    'ALTER TABLE role_zuoqi ADD COLUMN lucky_value INTEGER DEFAULT 0')
            if 'update_time' not in zuoqi_cols:
                self.db.execute(
                    'ALTER TABLE role_zuoqi ADD COLUMN update_time INTEGER DEFAULT 0')
            for column, declaration in (
                    ('fail_count', 'INTEGER DEFAULT 0'),
                    ('total_exp', 'INTEGER DEFAULT 0'),
                    ('free_jb', 'INTEGER DEFAULT 0'),
                    ('lucky_goods_id', 'TEXT'),
                    ('lucky_goods_expire_time', 'INTEGER DEFAULT 0'),
                    ('add_lucky_value', 'INTEGER DEFAULT 0'),
                    ('kaifu_data', 'TEXT'),
                    ('attribute_goods_id', 'TEXT')):
                if column not in zuoqi_cols:
                    self.db.execute(
                        f'ALTER TABLE role_zuoqi ADD COLUMN {column} {declaration}')
            rc_pk = [row['name'] for row in self.db.execute(
                'PRAGMA table_info(task_richang)') if row['pk']]
            if rc_pk != ['role_id']:
                # Legacy schema keyed the quest guid; the port keeps one
                # quest per role, so rebuild keyed on role_id, keeping the
                # latest quest when a role somehow holds several.
                self.db.execute(
                    'CREATE TABLE task_richang_new (\n'
                    '  role_id INTEGER PRIMARY KEY,\n'
                    '  id TEXT,\n'
                    '  condition_config_id TEXT,\n'
                    '  reward_config_id TEXT,\n'
                    '  reward_loop_config_id TEXT,\n'
                    '  task_condition TEXT,\n'
                    '  current_loop INTEGER DEFAULT 1,\n'
                    '  task_state INTEGER DEFAULT 0,\n'
                    '  fufei_state INTEGER DEFAULT 0,\n'
                    '  recevie_time INTEGER,\n'
                    '  create_time INTEGER,\n'
                    '  FOREIGN KEY(role_id) REFERENCES characters(id)'
                    ' ON DELETE CASCADE\n)')
                self.db.execute(
                    'INSERT INTO task_richang_new SELECT role_id, id,'
                    ' condition_config_id, reward_config_id,'
                    ' reward_loop_config_id, task_condition, current_loop,'
                    ' task_state, fufei_state, recevie_time, create_time'
                    ' FROM task_richang WHERE rowid IN (SELECT MAX(rowid)'
                    ' FROM task_richang GROUP BY role_id)')
                self.db.execute('DROP TABLE task_richang')
                self.db.execute(
                    'ALTER TABLE task_richang_new RENAME TO task_richang')
            self.db.commit()

    def create_account(self, username, pass_hash):
        with self.lock:
            try:
                self.db.execute(
                    'INSERT INTO accounts(username, pass_hash, created) VALUES(?,?,?)',
                    (username, pass_hash, int(time.time())))
            except sqlite3.IntegrityError:
                return False
            self.db.commit()
            return True

    def create_session(self, token, uid):
        with self.lock:
            self.db.execute(
                'INSERT OR REPLACE INTO sessions(token, uid, created) VALUES(?,?,?)',
                (token, uid, int(time.time())))
            self.db.commit()

    def get_session(self, token):
        with self.lock:
            row = self.db.execute(
                'SELECT token, uid, created FROM sessions WHERE token=?',
                (token,)).fetchone()
            return dict(row) if row else None

    def get_account(self, username):
        with self.lock:
            row = self.db.execute(
                'SELECT * FROM accounts WHERE username=?', (username,)).fetchone()
            return dict(row) if row else None

    def close(self):
        with self.lock:
            self.db.close()

    def create_character(self, account, server_id, name, job='A', sex=0,
                         face='', **state):
        """Insert a character and supplied authoritative state; returns its id."""
        unknown = set(state) - set(CHARACTER_COLUMNS)
        if unknown:
            raise ValueError(f'unknown character state fields: {sorted(unknown)}')
        fields = ['account', 'server_id', 'name', 'job', 'sex', 'face',
                  *state.keys(), 'created']
        values = [account, server_id, name, str(job), sex, face,
                  *state.values(), int(time.time())]
        placeholders = ','.join('?' for _ in fields)
        with self.lock:
            try:
                cur = self.db.execute(
                    f"INSERT INTO characters({','.join(fields)}) VALUES({placeholders})",
                    values)
                self.db.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None

    def update_character_state(self, role_id, **state):
        """Persist authoritative gameplay fields for an owned role ID.

        Migrated roles are known to the client by legacy_id while the row id
        stays numeric, and callers pass the wire id, so match either one.
        """
        if not state or set(state) - set(CHARACTER_COLUMNS):
            raise ValueError('state must contain known gameplay fields')
        fields = list(state)
        with self.lock:
            cur = self.db.execute(
                'UPDATE characters SET ' + ', '.join(f'{f}=?' for f in fields)
                + ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                [*state.values(), str(role_id), str(role_id)])
            self.db.commit()
            return cur.rowcount == 1

    def list_roles(self, account, server_id):
        """Roles for an account; a role_stage row wins over characters columns."""
        with self.lock:
            rows = self.db.execute(
                'SELECT c.id, c.legacy_id, c.name, c.job, c.sex, c.face, c.level,'
                ' c.exp, COALESCE(s.map_id, c.map_id) AS map_id,'
                ' COALESCE(s.map_x, c.map_x) AS map_x,'
                ' COALESCE(s.map_y, c.map_y) AS map_y,'
                ' COALESCE(s.hp, c.hp) AS hp, COALESCE(s.mp, c.mp) AS mp,'
                ' COALESCE(s.max_hp, c.max_hp) AS max_hp,'
                ' COALESCE(s.max_mp, c.max_mp) AS max_mp,'
                ' c.tongqian, c.bind_lingshi, c.lingshi, c.recive_yb,'
                ' c.zhenqi, c.shengwang,'
                ' COALESCE(s.shanbi_val, 0) AS shanbi_val,'
                ' s.zuoqi_info AS zuoqi_info,'
                ' c.created'
                ' FROM characters c LEFT JOIN role_stage s ON s.role_id=c.id'
                ' WHERE c.account=? AND c.server_id=? ORDER BY c.id',
                (account, server_id)).fetchall()
            return [dict(row) for row in rows]

    def get_role_equip(self, role_id):
        """Equipped rows for a role (legacy role_equip_slot subset)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT slot_num, goods_id, rare_level, item_level, attributes'
                ' FROM role_equip WHERE role_id=? ORDER BY slot_num',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def get_role_skills(self, role_id):
        """Owned skills for a role as [{category, level}] (legacy role_skill rows)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT category, level FROM role_skill WHERE role_id=?'
                ' ORDER BY skill_key',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_skill(self, role_id, category, level):
        """Learn/update one role_skill row keyed by category."""
        with self.lock:
            self.db.execute(
                'INSERT INTO role_skill(role_id, skill_key, category, level)'
                ' VALUES(?,?,?,?)'
                ' ON CONFLICT(role_id, skill_key) DO UPDATE SET'
                ' level=excluded.level',
                (str(role_id), str(category), str(category), int(level)))
            self.db.commit()
            return True

    def get_role_shenjiang(self, role_id):
        """Owned shenjiang rows for a role (legacy role_shenjiang subset)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT shenjiang_id, jiangxing_id, jiangxing_rank, skills,'
                ' jiangxing_state, cur_jiangxing_id, fail_count,'
                ' rank_fail_count, rank_lucky'
                ' FROM role_shenjiang WHERE role_id=? ORDER BY shenjiang_key',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_shenjiang(self, role_id, shenjiang_id, **state):
        """Upsert one owned shenjiang row keyed by (role, shenjiang id)."""
        fields = {'shenjiang_id': str(shenjiang_id), **state}
        unknown = set(fields) - {'shenjiang_id', 'jiangxing_id',
                                 'jiangxing_rank', 'skills', 'jiangxing_state',
                                 'cur_jiangxing_id', 'fail_count',
                                 'rank_fail_count', 'rank_lucky'}
        if unknown:
            raise ValueError(f'unknown shenjiang fields: {sorted(unknown)}')
        cols = ['shenjiang_key', 'shenjiang_id',
                *[k for k in fields if k != 'shenjiang_id']]
        vals = [str(shenjiang_id), str(shenjiang_id),
                *[fields[k] for k in cols[2:]]]
        sets = ', '.join(f'{c}=excluded.{c}' for c in cols[2:])
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_shenjiang(role_id, { ", ".join(cols)})'
                f' VALUES(?, { ", ".join("?" for _ in cols)})'
                f' ON CONFLICT(role_id, shenjiang_key) DO UPDATE SET {sets}',
                (str(role_id), *vals))
            self.db.commit()
            return True

    def get_role_chengjiu(self, role_id):
        """Claimed achievement rows for a role (legacy role_chengjiu subset)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT task_id, task_status FROM role_chengjiu'
                ' WHERE role_id=? ORDER BY task_id',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_chengjiu(self, role_id, task_id, task_status=1):
        """Upsert one claimed achievement keyed by (role, achievement id)."""
        with self.lock:
            self.db.execute(
                'INSERT INTO role_chengjiu(role_id, task_id, task_status)'
                ' VALUES(?,?,?)'
                ' ON CONFLICT(role_id, task_id) DO UPDATE SET'
                ' task_status=excluded.task_status',
                (str(role_id), str(task_id), int(task_status)))
            self.db.commit()
            return True

    def save_role_equip(self, role_id, items):
        """Replace a role's equipped rows; items carry slot/goods/levels/blob."""
        with self.lock:
            self.db.execute('DELETE FROM role_equip WHERE role_id=?',
                            (str(role_id),))
            for item in items or []:
                self.db.execute(
                    'INSERT INTO role_equip(role_id, slot_num, goods_id,'
                    ' rare_level, item_level, attributes)'
                    ' VALUES(?,?,?,?,?,?)',
                    (str(role_id), item.get('slot_num'), item.get('goods_id'),
                     item.get('rare_level') or 0, item.get('item_level') or 0,
                     item.get('attributes')))
            self.db.commit()
            return True

    def get_role_attr_buffs(self, role_id):
        """Attribute-pill rows for a role (legacy role_attribute_buff subset)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT attribute_id, count FROM role_attr_buff'
                ' WHERE role_id=? ORDER BY attribute_id',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_attr_buffs(self, role_id, buffs):
        """Replace a role's attribute-pill rows; buffs carry id + count."""
        with self.lock:
            self.db.execute('DELETE FROM role_attr_buff WHERE role_id=?',
                            (str(role_id),))
            for buff in buffs or []:
                self.db.execute(
                    'INSERT INTO role_attr_buff(role_id, attribute_id, count)'
                    ' VALUES(?,?,?)',
                    (str(role_id), buff.get('attribute_id'),
                     buff.get('count') or 0))
            self.db.commit()
            return True

    def get_role_vip(self, role_id):
        """VIP row for a role (legacy role_vip subset), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT vip_level, state_day, state_week, state_tejia,'
                ' prop_value, tody_prop_value, prop_use_time, day_time, week_time'
                ' FROM role_vip WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def get_role_vip_kaifu(self, role_id):
        """Kaifu lottery row for a role, or None when never ensured."""
        with self.lock:
            row = self.db.execute(
                'SELECT lingqu_reward, lotter_reward FROM role_vip_kaifu'
                ' WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_vip_kaifu(self, role_id, **fields):
        """Upsert a role's kaifu row; only known columns."""
        allowed = {'lingqu_reward', 'lotter_reward'}
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown kaifu fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_vip_kaifu(role_id,{names})'
                f' VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def save_role_vip(self, role_id, **fields):
        """Upsert a role's VIP row; only known role_vip columns."""
        allowed = {'vip_level', 'state_day', 'state_week', 'state_tejia',
                   'prop_value', 'tody_prop_value', 'prop_use_time',
                   'day_time', 'week_time'}
        if not fields or set(fields) - allowed:
            raise ValueError(f'unknown vip fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_vip(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_juqing(self, role_id):
        """Story-dungeon row for a role, or None when never challenged."""
        with self.lock:
            row = self.db.execute(
                'SELECT passed_highest_id, passed_ids_daily, auto_pass_info,'
                ' best_passed_info, refresh_time, award_info, tiaozhan_jindu,'
                ' pending_award'
                ' FROM role_juqingfuben WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_juqing(self, role_id, **fields):
        """Upsert a role's story-dungeon row; only known columns."""
        allowed = {'passed_highest_id', 'passed_ids_daily', 'auto_pass_info',
                   'best_passed_info', 'refresh_time', 'award_info',
                   'tiaozhan_jindu', 'pending_award'}
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown juqing fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_juqingfuben(role_id,{names})'
                f' VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_zuwufuben(self, role_id):
        """Clan-dungeon row for a role, or None when never entered."""
        with self.lock:
            row = self.db.execute(
                'SELECT pass_max_id, everyday_pass_data, everyday_time,'
                ' buy_count_data, saodang_data'
                ' FROM role_zuwufuben WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_zuwufuben(self, role_id, **fields):
        """Upsert a role's clan-dungeon row; only known columns."""
        allowed = {'pass_max_id', 'everyday_pass_data', 'everyday_time',
                   'buy_count_data', 'saodang_data'}
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown zuwufuben fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_zuwufuben(role_id,{names})'
                f' VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_zuwu(self, role_id, zuwu_id):
        """One activated clan guardian, or None when never activated."""
        with self.lock:
            row = self.db.execute(
                'SELECT zuwu_id, level, exp, jieshu, fail_count'
                ' FROM role_zuwu WHERE role_id=? AND zuwu_id=?',
                (str(role_id), str(zuwu_id))).fetchone()
            return dict(row) if row else None

    def list_role_zuwu(self, role_id):
        """All activated clan guardians of a role."""
        with self.lock:
            rows = self.db.execute(
                'SELECT zuwu_id, level, exp, jieshu, fail_count'
                ' FROM role_zuwu WHERE role_id=?',
                (str(role_id),)).fetchall()
            return [dict(r) for r in rows]

    def save_role_zuwu(self, role_id, zuwu_id, **fields):
        """Upsert one clan guardian; only known columns."""
        allowed = {'level', 'exp', 'jieshu', 'fail_count'}
        if set(fields) - allowed:
            raise ValueError(
                f'unknown zuwu fields: {sorted(set(fields) - allowed)}')
        with self.lock:
            self.db.execute(
                'INSERT INTO role_zuwu(role_id, zuwu_id) VALUES(?,?)'
                ' ON CONFLICT(role_id, zuwu_id) DO NOTHING',
                (str(role_id), str(zuwu_id)))
            for key, val in fields.items():
                self.db.execute(
                    f'UPDATE role_zuwu SET {key}=?'
                    ' WHERE role_id=? AND zuwu_id=?',
                    (val, str(role_id), str(zuwu_id)))
            self.db.commit()
            return True

    def add_role_bag_dummy(self, role_id, goods_id, count):
        """Increment a bag-dummy count (Java bagdummy addGoods)."""
        try:
            delta = int(count)
        except (TypeError, ValueError):
            return False
        if delta <= 0 or not str(goods_id or '').strip():
            return False
        gid = str(goods_id)
        with self.lock:
            row = self.db.execute(
                'SELECT goods_count FROM role_bag_dummy'
                ' WHERE role_id=? AND goods_id=?',
                (str(role_id), gid)).fetchone()
            if row is None:
                self.db.execute(
                    'INSERT INTO role_bag_dummy(id, role_id, goods_id,'
                    ' goods_count) VALUES(?,?,?,?)',
                    (f'{role_id}:{gid}', str(role_id), gid, delta))
            else:
                self.db.execute(
                    'UPDATE role_bag_dummy SET goods_count=goods_count+?'
                    ' WHERE role_id=? AND goods_id=?',
                    (delta, str(role_id), gid))
            self.db.commit()
            return True

    def get_role_qq_list(self, role_id):
        """QQ-member binding row for a role, or None when never bound."""
        with self.lock:
            row = self.db.execute(
                'SELECT qq, user_name, is_get_rewards FROM role_qq_list'
                ' WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_qq_list(self, role_id, **fields):
        """Upsert a role's QQ-member row; only known role_qq_list columns."""
        allowed = {'qq', 'user_name', 'is_get_rewards'}
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown qq list fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_qq_list(role_id,{names})'
                f' VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_vip_qq(self):
        """Active QQ-member config (first vip_qq row), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT id, min_recharge, pic, qq FROM vip_qq'
                ' ORDER BY id LIMIT 1').fetchone()
            return dict(row) if row else None

    def save_vip_qq(self, min_recharge=0, pic=None, qq=None):
        """Insert a vip_qq config row; first row wins like DataContainer."""
        with self.lock:
            self.db.execute(
                'INSERT INTO vip_qq(min_recharge, pic, qq)'
                ' VALUES(?,?,?)',
                (min_recharge, pic, qq))
            self.db.commit()
            return True

    def get_role_loginlibao(self, role_id):
        """Login gift-pack row for a role, or None when never claimed."""
        with self.lock:
            row = self.db.execute(
                'SELECT lingqujson, lingqu_time FROM role_loginlibao'
                ' WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_loginlibao(self, role_id, **fields):
        """Upsert a role's loginlibao row; only known columns."""
        allowed = {'lingqujson', 'lingqu_time'}
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown loginlibao fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_loginlibao(role_id,{names})'
                f' VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_lvlibao(self, role_id):
        """Level gift-pack row for a role, or None when never claimed."""
        with self.lock:
            row = self.db.execute(
                'SELECT state FROM role_lvlibao WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_lvlibao(self, role_id, **fields):
        """Upsert a role's lvlibao row; only known columns."""
        allowed = {'state'}
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown lvlibao fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_lvlibao(role_id,{names})'
                f' VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def list_role_email(self, role_id):
        """Mail rows for a role, oldest first; empty when none."""
        with self.lock:
            rows = self.db.execute(
                'SELECT id, system_email_id, title, content, attachment, jb,'
                ' yb, is_read, is_claimed, created FROM role_email'
                ' WHERE role_id=? ORDER BY id',
                (str(role_id),)).fetchall()
            return [dict(r) for r in rows]

    def get_role_email(self, role_id, mail_id):
        """One mail row for a role, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT id, system_email_id, title, content, attachment, jb,'
                ' yb, is_read, is_claimed, created FROM role_email'
                ' WHERE role_id=? AND id=?',
                (str(role_id), str(mail_id))).fetchone()
            return dict(row) if row else None

    def save_role_email(self, role_id, title='', content='',
                        attachment='', system_email_id=0, jb=0, yb=0):
        """Insert a mail row for a role; returns the new id."""
        import time as _time
        with self.lock:
            cur = self.db.execute(
                'INSERT INTO role_email(role_id, system_email_id, title,'
                ' content, attachment, jb, yb, created)'
                ' VALUES(?,?,?,?,?,?,?,?)',
                (str(role_id), str(system_email_id), title, content,
                 attachment, int(jb or 0), int(yb or 0),
                 int(_time.time() * 1000)))
            self.db.commit()
            return cur.lastrowid

    def update_role_email(self, role_id, mail_id, **fields):
        """Update read/claimed flags on a role's mail row."""
        allowed = {'is_read', 'is_claimed', 'attachment', 'jb', 'yb'}
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown email fields: {sorted(set(fields) - allowed)}')
        sets = ', '.join(f'{n}=?' for n in fields)
        with self.lock:
            self.db.execute(
                f'UPDATE role_email SET {sets} WHERE role_id=? AND id=?',
                [*fields.values(), str(role_id), str(mail_id)])
            self.db.commit()
            return True

    def delete_role_email(self, role_id, mail_id):
        """Delete one mail row for a role."""
        with self.lock:
            self.db.execute(
                'DELETE FROM role_email WHERE role_id=? AND id=?',
                (str(role_id), str(mail_id)))
            self.db.commit()
            return True

    def _get_simple_row(self, table, role_id, cols):
        """One role-keyed row as a dict, or None."""
        with self.lock:
            row = self.db.execute(
                f'SELECT {cols} FROM {table} WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def _save_simple_row(self, table, role_id, allowed, fields):
        """Upsert a role-keyed row; only known columns."""
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown {table} fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO {table}(role_id,{names})'
                f' VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_loginlingjiang(self, role_id):
        """Login-streak row for a role, or None."""
        return self._get_simple_row(
            'role_loginlingjiang', role_id, 'day_number, lingqujson')

    def save_role_loginlingjiang(self, role_id, **fields):
        """Upsert a role's loginlingjiang row."""
        return self._save_simple_row(
            'role_loginlingjiang', role_id, {'day_number', 'lingqujson'},
            fields)

    def get_role_touxian(self, role_id):
        """Title row for a role, or None."""
        return self._get_simple_row(
            'role_touxian', role_id, 'peidai_id, jihuoids')

    def save_role_touxian(self, role_id, **fields):
        """Upsert a role's title row."""
        return self._save_simple_row(
            'role_touxian', role_id, {'peidai_id', 'jihuoids'}, fields)

    def get_role_guangyi(self, role_id):
        """Wing row for a role, or None."""
        return self._get_simple_row(
            'role_guangyi', role_id,
            'peidai_id, level, lucky, ispeidai, attr_dan')

    def save_role_guangyi(self, role_id, **fields):
        """Upsert a role's wing row."""
        return self._save_simple_row(
            'role_guangyi', role_id,
            {'peidai_id', 'level', 'lucky', 'ispeidai', 'attr_dan'},
            fields)

    def get_role_qibing(self, role_id):
        """Qibing progression row for a role, or None."""
        return self._get_simple_row(
            'role_qizhanbinqi', role_id,
            'binqi_level, fail_count, lucky_value, upgrade_time,'
            ' lingqu_time, update_time, attribute_dan')

    def save_role_qibing(self, role_id, **fields):
        """Upsert a role's qibing progression row."""
        return self._save_simple_row(
            'role_qizhanbinqi', role_id,
            {'binqi_level', 'fail_count', 'lucky_value', 'upgrade_time',
             'lingqu_time', 'update_time', 'attribute_dan'},
            fields)

    def get_role_baixian(self, role_id):
        """Worship-count row for a role, or None."""
        return self._get_simple_row(
            'role_baixian', role_id, 'counts, last_day')

    def save_role_baixian(self, role_id, **fields):
        """Upsert a role's worship row."""
        return self._save_simple_row(
            'role_baixian', role_id, {'counts', 'last_day'}, fields)

    def get_role_kapai(self, role_id):
        """Kapai reward-state row for a role, or None."""
        return self._get_simple_row('role_kapai', role_id, 'state')

    def save_role_kapai(self, role_id, **fields):
        """Upsert a role's kapai row."""
        return self._save_simple_row('role_kapai', role_id, {'state'},
                                     fields)

    def get_role_dafuwong(self, role_id):
        """Dafuwong board-state row for a role, or None."""
        return self._get_simple_row(
            'role_dafuwong', role_id,
            'slot, grade, zanshi, roll_count, tongqian_count,'
            ' last_roll_ms')

    def save_role_dafuwong(self, role_id, **fields):
        """Upsert a role's dafuwong row."""
        return self._save_simple_row(
            'role_dafuwong', role_id,
            {'slot', 'grade', 'zanshi', 'roll_count', 'tongqian_count',
             'last_roll_ms'},
            fields)

    def get_role_xianshibuy(self, role_id):
        """Timed-shop purchase row for a role, or None."""
        return self._get_simple_row(
            'role_xianshibuy', role_id, 'buy_data, buy_day')

    def save_role_xianshibuy(self, role_id, **fields):
        """Upsert a role's xianshibuy row."""
        return self._save_simple_row(
            'role_xianshibuy', role_id, {'buy_data', 'buy_day'}, fields)

    def get_xianshi_buy(self):
        """Server-wide sold-count row, or None before the first sale."""
        with self.lock:
            row = self.db.execute(
                "SELECT buy_data FROM xianshi_buy WHERE id='global'"
            ).fetchone()
            return dict(row) if row else None

    def save_xianshi_buy(self, buy_data):
        """Upsert the server-wide sold-count row."""
        with self.lock:
            self.db.execute(
                'INSERT INTO xianshi_buy(id, buy_data) VALUES(\'global\', ?)'
                ' ON CONFLICT(id) DO UPDATE SET buy_data=excluded.buy_data',
                (str(buy_data),))
            self.db.commit()
            return True

    def get_role_zhuihui(self, role_id):
        """Recovery-claim row for a role, or None."""
        return self._get_simple_row(
            'role_zhuihui', role_id, 'state')

    def save_role_zhuihui(self, role_id, **fields):
        """Upsert a role's zhuihui row."""
        return self._save_simple_row(
            'role_zhuihui', role_id, {'state'}, fields)

    def get_role_jianding(self, role_id):
        """Appraisal state row for a role, or None when never appraised."""
        with self.lock:
            row = self.db.execute(
                'SELECT jianding_count, jianding_time, jianding_exp,'
                ' hecheng_count, hecheng_time FROM role_jianding'
                ' WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_jianding(self, role_id, **fields):
        """Upsert a role's appraisal state; only known columns."""
        allowed = {'jianding_count', 'jianding_time', 'jianding_exp',
                   'hecheng_count', 'hecheng_time'}
        if not fields or set(fields) - allowed:
            raise ValueError(
                f'unknown jianding fields: {sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_jianding(role_id,{names})'
                f' VALUES(?,{placeholders})'
                f' ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_xianjiechenhao(self, role_id):
        """Xianjie/chenghao id row for a role, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT xianjie_id, chenhao_id FROM role_xianjiechenhao'
                ' WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_xianjiechenhao(self, role_id, xianjie_id=None,
                                 chenhao_id=None):
        """Upsert a role's xianjie/chenghao id lists (JSON texts)."""
        with self.lock:
            self.db.execute(
                'INSERT INTO role_xianjiechenhao(role_id, xianjie_id, chenhao_id)'
                ' VALUES(?,?,?)'
                ' ON CONFLICT(role_id) DO UPDATE SET'
                ' xianjie_id=excluded.xianjie_id, chenhao_id=excluded.chenhao_id',
                (str(role_id), xianjie_id, chenhao_id))
            self.db.commit()
            return True

    def get_role_pets(self, role_id):
        """Pet rows for a role as [{pet_id, pet_lv, pet_rank, pet_lv_exp,
        pet_rank_exp}] in insertion order (RolePetDao.cacheLoadAll)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT pet_id, pet_lv, pet_rank, pet_lv_exp, pet_rank_exp'
                ' FROM role_pet WHERE role_id=? ORDER BY rowid',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_pet(self, role_id, pet_id, pet_lv=None, pet_lv_exp=None,
                      pet_rank=None, pet_rank_exp=None, pet_rank_fail=None,
                      pet_rank_update_time=None, create_time=None,
                      row_id=None):
        """Upsert a role's pet row keyed by (role_id, pet_id)."""
        with self.lock:
            row = self.db.execute(
                'SELECT id FROM role_pet WHERE role_id=? AND pet_id=?',
                (str(role_id), str(pet_id))).fetchone()
            rid = row['id'] if row else (row_id or f'pet{uuid.uuid4().hex}')
            self.db.execute(
                'INSERT INTO role_pet(id, role_id, pet_id, pet_lv,'
                ' pet_lv_exp, pet_rank, pet_rank_exp, pet_rank_fail,'
                ' pet_rank_update_time, create_time)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?)'
                ' ON CONFLICT(id) DO UPDATE SET'
                ' pet_lv=excluded.pet_lv,'
                ' pet_lv_exp=excluded.pet_lv_exp,'
                ' pet_rank=excluded.pet_rank,'
                ' pet_rank_exp=excluded.pet_rank_exp,'
                ' pet_rank_fail=excluded.pet_rank_fail,'
                ' pet_rank_update_time=excluded.pet_rank_update_time,'
                ' create_time=excluded.create_time',
                (str(rid), str(role_id), str(pet_id), pet_lv, pet_lv_exp,
                 pet_rank, pet_rank_exp, pet_rank_fail,
                 pet_rank_update_time, create_time))
            self.db.commit()
            return str(rid)

    def get_role_pet_zhenfa(self, role_id):
        """Formation row for a role (legacy role_pet_zhenfa subset), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT zhenfa_id, pet_chuzhan_id, upgrade_exp,'
                ' jinjie_fail_count, jinjie_time, jinjie_data, zhenfa_pet,'
                ' pet_upgrade_count, pet_upgrade_time'
                ' FROM role_pet_zhenfa WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_pet_zhenfa(self, role_id, zhenfa_id=None,
                             pet_chuzhan_id=None, upgrade_exp=None,
                             jinjie_fail_count=None, jinjie_time=None,
                             jinjie_data=None, zhenfa_pet=None,
                             pet_upgrade_count=None, pet_upgrade_time=None):
        """Upsert a role's pet formation row."""
        with self.lock:
            self.db.execute(
                'INSERT INTO role_pet_zhenfa(role_id, zhenfa_id,'
                ' pet_chuzhan_id, upgrade_exp, jinjie_fail_count,'
                ' jinjie_time, jinjie_data, zhenfa_pet, pet_upgrade_count,'
                ' pet_upgrade_time)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?)'
                ' ON CONFLICT(role_id) DO UPDATE SET'
                ' zhenfa_id=excluded.zhenfa_id,'
                ' pet_chuzhan_id=excluded.pet_chuzhan_id,'
                ' upgrade_exp=excluded.upgrade_exp,'
                ' jinjie_fail_count=excluded.jinjie_fail_count,'
                ' jinjie_time=excluded.jinjie_time,'
                ' jinjie_data=excluded.jinjie_data,'
                ' zhenfa_pet=excluded.zhenfa_pet,'
                ' pet_upgrade_count=excluded.pet_upgrade_count,'
                ' pet_upgrade_time=excluded.pet_upgrade_time',
                (str(role_id), zhenfa_id, pet_chuzhan_id, upgrade_exp,
                 jinjie_fail_count, jinjie_time, jinjie_data, zhenfa_pet,
                 pet_upgrade_count, pet_upgrade_time))
            self.db.commit()
            return True

    def get_role_zuoqi(self, role_id):
        """Mount-rank row for a role (legacy role_zuoqi subset), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT zuoqi_rank, zuoqi_cur_rank, lucky_value, update_time,'
                ' fail_count, total_exp, free_jb, lucky_goods_id,'
                ' lucky_goods_expire_time, add_lucky_value, kaifu_data,'
                ' attribute_goods_id'
                ' FROM role_zuoqi WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_zuoqi(self, role_id, zuoqi_rank=None, zuoqi_cur_rank=None,
                        lucky_value=None, update_time=None, fail_count=None,
                        total_exp=None, free_jb=None, lucky_goods_id=None,
                        lucky_goods_expire_time=None, add_lucky_value=None,
                        kaifu_data=None, attribute_goods_id=None):
        """Upsert a role's mount row (rank/cur_rank/blessing/pity/kaifu)."""
        with self.lock:
            self.db.execute(
                'INSERT INTO role_zuoqi(role_id, zuoqi_rank, zuoqi_cur_rank,'
                ' lucky_value, update_time, fail_count, total_exp, free_jb,'
                ' lucky_goods_id, lucky_goods_expire_time, add_lucky_value,'
                ' kaifu_data, attribute_goods_id)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)'
                ' ON CONFLICT(role_id) DO UPDATE SET'
                ' zuoqi_rank=excluded.zuoqi_rank,'
                ' zuoqi_cur_rank=excluded.zuoqi_cur_rank,'
                ' lucky_value=excluded.lucky_value,'
                ' update_time=excluded.update_time,'
                ' fail_count=excluded.fail_count,'
                ' total_exp=excluded.total_exp,'
                ' free_jb=excluded.free_jb,'
                ' lucky_goods_id=excluded.lucky_goods_id,'
                ' lucky_goods_expire_time=excluded.lucky_goods_expire_time,'
                ' attribute_goods_id=excluded.attribute_goods_id,'
                ' add_lucky_value=excluded.add_lucky_value,'
                ' kaifu_data=excluded.kaifu_data',
                (str(role_id), zuoqi_rank, zuoqi_cur_rank, lucky_value,
                 update_time, fail_count, total_exp, free_jb, lucky_goods_id,
                 lucky_goods_expire_time, add_lucky_value, kaifu_data,
                 attribute_goods_id))
            self.db.commit()
            return True

    def get_zuoqi_fanhuan(self):
        """Refund-feed rows as [[role_name, count]] (insertion order)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT role_name, goods_count FROM zuoqi_fanhuan'
                ' ORDER BY id').fetchall()
            return [[r['role_name'], r['goods_count']] for r in rows]

    def save_zuoqi_fanhuan(self, role_name, goods_count):
        """Append one refund-feed row (ZuoqiFanhuanDaoImpl.insert2Db)."""
        with self.lock:
            self.db.execute(
                'INSERT INTO zuoqi_fanhuan(role_name, goods_count)'
                ' VALUES(?,?)',
                (str(role_name), goods_count))
            self.db.commit()
            return True

    def get_role_bag_slots(self, role_id, min_slot=1, max_slot=150):
        """Bag slot rows for a role in [min_slot, max_slot] (slot order)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT slot_num, bag_id, goods_id, count, bind, expire_time,'
                ' rare_level, item_level, attributes FROM role_bag_slot'
                ' WHERE role_id=? AND slot_num>=? AND slot_num<=?'
                ' ORDER BY slot_num',
                (str(role_id), min_slot, max_slot)).fetchall()
            return [dict(row) for row in rows]

    def save_role_bag_slots(self, role_id, rows):
        """Replace a role's bag slot rows; rows carry slot/goods/count/blob."""
        with self.lock:
            self.db.execute('DELETE FROM role_bag_slot WHERE role_id=?',
                            (str(role_id),))
            for row in rows or []:
                if row.get('slot_num') is None or not row.get('goods_id'):
                    continue
                # Locally created rows need a stable row id: Java's IdGen
                # issues one at creation, and moveGoodses looks rows up by it.
                bag_id = row.get('bag_id') or f'py{uuid.uuid4().hex[:16]}'
                self.db.execute(
                    'INSERT INTO role_bag_slot(role_id, slot_num, bag_id, goods_id,'
                    ' count, bind, expire_time, rare_level, item_level, attributes)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (str(role_id), row.get('slot_num'), bag_id,
                     row.get('goods_id'), row.get('count') or 0,
                     row.get('bind') or 0, row.get('expire_time'),
                     row.get('rare_level') or 0, row.get('item_level') or 0,
                     row.get('attributes')))
            self.db.commit()
            return True

    def get_role_bag_slot(self, role_id, slot_num):
        """One bag slot row for a role, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT slot_num, bag_id, goods_id, count, bind, expire_time,'
                ' rare_level, item_level, attributes FROM role_bag_slot'
                ' WHERE role_id=? AND slot_num=?',
                (str(role_id), slot_num)).fetchone()
            return dict(row) if row else None

    def get_role_bag_slot_by_bag_id(self, role_id, bag_id):
        """One bag slot row by its legacy row id, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT slot_num, bag_id, goods_id, count, bind, expire_time,'
                ' rare_level, item_level, attributes FROM role_bag_slot'
                ' WHERE role_id=? AND bag_id=?',
                (str(role_id), bag_id)).fetchone()
            return dict(row) if row else None

    def update_role_bag_slot(self, role_id, slot_num, **fields):
        """Update known columns of one bag slot row."""
        known = {'bag_id', 'goods_id', 'count', 'bind', 'expire_time',
                 'rare_level', 'item_level', 'attributes'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known bag slot columns')
        sets = ', '.join(f'{f}=?' for f in fields)
        with self.lock:
            cur = self.db.execute(
                f'UPDATE role_bag_slot SET {sets}'
                ' WHERE role_id=? AND slot_num=?',
                [*fields.values(), str(role_id), slot_num])
            self.db.commit()
            return cur.rowcount == 1

    def move_role_bag_slot(self, role_id, from_slot, to_slot):
        """Move a bag row between slots (swap when occupied)."""
        with self.lock:
            src = self.db.execute(
                'SELECT * FROM role_bag_slot WHERE role_id=? AND slot_num=?',
                (str(role_id), from_slot)).fetchone()
            if src is None:
                return False
            dst = self.db.execute(
                'SELECT slot_num FROM role_bag_slot WHERE role_id=? AND slot_num=?',
                (str(role_id), to_slot)).fetchone()
            if dst is None:
                self.db.execute(
                    'UPDATE role_bag_slot SET slot_num=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (to_slot, str(role_id), from_slot))
            else:
                self.db.execute(
                    'UPDATE role_bag_slot SET slot_num=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (-1, str(role_id), to_slot))
                self.db.execute(
                    'UPDATE role_bag_slot SET slot_num=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (to_slot, str(role_id), from_slot))
                self.db.execute(
                    'UPDATE role_bag_slot SET slot_num=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (from_slot, str(role_id), -1))
            self.db.commit()
            return True

    def insert_role_bag_slot(self, role_id, row):
        """Insert one bag slot row; returns its row id (generated when absent)."""
        bag_id = row.get('bag_id') or f'py{uuid.uuid4().hex[:16]}'
        with self.lock:
            self.db.execute(
                'INSERT INTO role_bag_slot(role_id, slot_num, bag_id, goods_id,'
                ' count, bind, expire_time, rare_level, item_level, attributes)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                (str(role_id), row.get('slot_num'), bag_id,
                 row.get('goods_id'), row.get('count') or 0,
                 row.get('bind') or 0, row.get('expire_time'),
                 row.get('rare_level') or 0, row.get('item_level') or 0,
                 row.get('attributes')))
            self.db.commit()
            return bag_id

    def delete_role_bag_slot(self, role_id, slot_num):
        """Delete one bag slot row."""
        with self.lock:
            cur = self.db.execute(
                'DELETE FROM role_bag_slot WHERE role_id=? AND slot_num=?',
                (str(role_id), slot_num))
            self.db.commit()
            return cur.rowcount == 1

    def rewrite_role_bag_slots(self, role_id, rows, min_slot, max_slot):
        """Replace a role's slot rows in [min_slot, max_slot] with rows.

        The tidy-up compacts renumbered, merged rows back in one step; row
        ids are kept (Java updates the same entities) and rows left out of
        the rewrite (merged-away, zero-count) disappear with the delete.
        """
        with self.lock:
            self.db.execute(
                'DELETE FROM role_bag_slot'
                ' WHERE role_id=? AND slot_num>=? AND slot_num<=?',
                (str(role_id), min_slot, max_slot))
            for row in rows or []:
                if row.get('slot_num') is None or not row.get('goods_id') \
                        or not row.get('bag_id'):
                    continue
                self.db.execute(
                    'INSERT INTO role_bag_slot(role_id, slot_num, bag_id, goods_id,'
                    ' count, bind, expire_time, rare_level, item_level, attributes)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (str(role_id), row.get('slot_num'), row.get('bag_id'),
                     row.get('goods_id'), row.get('count') or 0,
                     row.get('bind') or 0, row.get('expire_time'),
                     row.get('rare_level') or 0, row.get('item_level') or 0,
                     row.get('attributes')))
            self.db.commit()
            return True

    def get_task_main(self, role_id):
        """A role's running main quest (legacy task_main subset), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT task_uid, task_id, state, condition, recevie_time,'
                ' create_time FROM task_main WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_task_main(self, role_id, **fields):
        """Upsert a role's running main quest (known columns only)."""
        known = {'task_uid', 'task_id', 'state', 'condition',
                 'recevie_time', 'create_time'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known task_main columns')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO task_main(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_task_taofa(self, role_id, task_uid):
        """One taofa quest row for a role, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT id, task_id, master_count, task_state, ts_state,'
                ' ts_reward_jb, ts_reward_exp, ts_reward_zhenqi,'
                ' ts_reward_bing_yb, ts_reward_prestige, update_time,'
                ' create_time FROM task_taofa WHERE role_id=? AND id=?',
                (str(role_id), str(task_uid))).fetchone()
            return dict(row) if row else None

    def get_task_taofas(self, role_id):
        """All taofa quest rows for a role, id order."""
        with self.lock:
            rows = self.db.execute(
                'SELECT id, task_id, master_count, task_state, ts_state,'
                ' ts_reward_jb, ts_reward_exp, ts_reward_zhenqi,'
                ' ts_reward_bing_yb, ts_reward_prestige, update_time,'
                ' create_time FROM task_taofa WHERE role_id=? ORDER BY id',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def insert_task_taofa(self, role_id, row):
        """Insert one taofa quest row."""
        with self.lock:
            self.db.execute(
                'INSERT INTO task_taofa(id, role_id, task_id, master_count,'
                ' task_state, ts_state, ts_reward_jb, ts_reward_exp,'
                ' ts_reward_zhenqi, ts_reward_bing_yb, ts_reward_prestige,'
                ' update_time, create_time)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (row.get('id'), str(role_id), row.get('task_id'),
                 row.get('master_count') or 0, row.get('task_state') or 0,
                 row.get('ts_state') or 0, row.get('ts_reward_jb') or 0,
                 row.get('ts_reward_exp') or 0,
                 row.get('ts_reward_zhenqi') or 0,
                 row.get('ts_reward_bing_yb') or 0,
                 row.get('ts_reward_prestige') or 0,
                 row.get('update_time'), row.get('create_time')))
            self.db.commit()
            return True

    def update_task_taofa(self, role_id, task_uid, **fields):
        """Update one taofa quest row (known columns only)."""
        known = {'task_id', 'master_count', 'task_state', 'ts_state',
                 'ts_reward_jb', 'ts_reward_exp', 'ts_reward_zhenqi',
                 'ts_reward_bing_yb', 'ts_reward_prestige', 'update_time',
                 'create_time'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known task_taofa columns')
        updates = ', '.join(f'{n}=?' for n in fields)
        with self.lock:
            self.db.execute(
                f'UPDATE task_taofa SET {updates} WHERE role_id=? AND id=?',
                [*fields.values(), str(role_id), str(task_uid)])
            self.db.commit()
            return True

    def delete_task_taofa(self, role_id, task_uid):
        """Delete one taofa quest row."""
        with self.lock:
            self.db.execute(
                'DELETE FROM task_taofa WHERE role_id=? AND id=?',
                (str(role_id), str(task_uid)))
            self.db.commit()
            return True

    def get_task_taofa_state(self, role_id):
        """A role's daily taofa counters, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT tunshi_count, hebing_count, finish_count,'
                ' total_count, create_time FROM task_taofa_state'
                ' WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_task_taofa_state(self, role_id, **fields):
        """Upsert a role's daily taofa counters (known columns only)."""
        known = {'tunshi_count', 'hebing_count', 'finish_count',
                 'total_count', 'create_time'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known task_taofa_state columns')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                'INSERT INTO task_taofa_state(role_id,'
                f'{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_task_richang(self, role_id):
        """A role's daily richang quest, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT id, condition_config_id, reward_config_id,'
                ' reward_loop_config_id, task_condition, current_loop,'
                ' task_state, fufei_state, recevie_time, create_time'
                ' FROM task_richang WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_task_richang(self, role_id, **fields):
        """Upsert a role's daily richang quest (known columns only)."""
        known = {'id', 'condition_config_id', 'reward_config_id',
                 'reward_loop_config_id', 'task_condition', 'current_loop',
                 'task_state', 'fufei_state', 'recevie_time', 'create_time'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known task_richang columns')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO task_richang(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def delete_task_richang(self, role_id):
        """Delete a role's daily richang quest."""
        with self.lock:
            self.db.execute(
                'DELETE FROM task_richang WHERE role_id=?',
                (str(role_id),))
            self.db.commit()
            return True

    def get_role_pozhen(self, role_id):
        """A role's formation row, or None (RolePozhen.daoLoad)."""
        with self.lock:
            row = self.db.execute(
                'SELECT max_location, locations, can_use_count, buy_count,'
                ' refresh_count, in_mopup, sd_main_id, mopup_time,'
                ' recovery_time, refresh_time, award_rate, expire_time'
                ' FROM role_pozhen WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_pozhen(self, role_id, **fields):
        """Upsert a role's formation row (known columns only)."""
        known = {'max_location', 'locations', 'can_use_count', 'buy_count',
                 'refresh_count', 'in_mopup', 'sd_main_id', 'mopup_time',
                 'recovery_time', 'refresh_time', 'award_rate', 'expire_time'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known role_pozhen columns')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_pozhen(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_task_gonghui(self, role_id):
        """A role's guild-task quest, or None (RoleGonghuiTask.daoLoad)."""
        with self.lock:
            row = self.db.execute(
                'SELECT id, condition_config_id, reward_config_id,'
                ' reward_loop_config_id, task_condition, current_loop,'
                ' task_state, fufei_state, recevie_time, create_time'
                ' FROM task_gonghui WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_task_gonghui(self, role_id, **fields):
        """Upsert a role's guild-task quest (known columns only)."""
        known = {'id', 'condition_config_id', 'reward_config_id',
                 'reward_loop_config_id', 'task_condition', 'current_loop',
                 'task_state', 'fufei_state', 'recevie_time', 'create_time'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known task_gonghui columns')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO task_gonghui(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def delete_task_gonghui(self, role_id):
        """Delete a role's guild-task quest."""
        with self.lock:
            self.db.execute(
                'DELETE FROM task_gonghui WHERE role_id=?',
                (str(role_id),))
            self.db.commit()
            return True

    def get_role_huodong(self, role_id):
        """A role's activity row, or None (RoleHuodong.daoLoad)."""
        with self.lock:
            row = self.db.execute(
                'SELECT role_id, max_count, day_count, mall_buy_count,'
                ' pay_yb FROM role_huodong WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_huodong(self, role_id, **fields):
        """Upsert a role's activity row (known columns only)."""
        known = {'max_count', 'day_count', 'mall_buy_count', 'pay_yb'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known role_huodong columns')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_huodong(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_huodong_info(self, huodong_id):
        """Global activity row, or None (HuodongInfo.dbLoad)."""
        with self.lock:
            row = self.db.execute(
                'SELECT huodong_id, mall_sell_info FROM huodong_info'
                ' WHERE huodong_id=?',
                (str(huodong_id),)).fetchone()
            return dict(row) if row else None

    def save_huodong_info(self, huodong_id, mall_sell_info):
        """Upsert a global activity row (HuodongInfo.dbUpdate)."""
        with self.lock:
            self.db.execute(
                'INSERT INTO huodong_info(huodong_id, mall_sell_info)'
                ' VALUES(?,?) ON CONFLICT(huodong_id) DO UPDATE'
                ' SET mall_sell_info=excluded.mall_sell_info',
                (str(huodong_id), str(mall_sell_info or '')))
            self.db.commit()
            return True

    # YB's MoneyType.getIntType (the sqlmap hardcodes money_type = 2).
    RECHARGE_MONEY_YB = 2

    @staticmethod
    def _recharge_role_scope(role):
        """(user_guid, server_id) a charge total scopes to for a role row."""
        return str(role.get('account') or ''), str(role.get('server_id') or '')

    def _recharge_role(self, role_id):
        """Character row for a wire id, or None (success totals need it)."""
        return self.db.execute(
            'SELECT id, account, server_id FROM characters'
            ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
            (str(role_id), str(role_id))).fetchone()

    def save_recharge_yb(self, server_id, user_guid, role_id, order_id,
                         rmb, money_num, is_calc, platform_type,
                         recharge_type, recharge_state, create_ms=None):
        """Insert one recharge_record row; returns its id.

        Record half of saveRechargetYb (no currency grant, no
        event): state '0' granted, '1' pending grant, '9' revoked,
        '1001'/'1003'/'1004'/'1005' failed. create_time is ms epoch.
        """
        if create_ms is None:
            create_ms = int(time.time() * 1000)
        record_id = uuid.uuid4().hex
        with self.lock:
            self.db.execute(
                'INSERT INTO recharge_record(id, user_role_id, rmb,'
                ' money_type, money_num, is_calc, recharge_type,'
                ' platform_type, recharge_state, order_id, create_time,'
                ' server_id, user_guid)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (record_id, str(role_id), float(rmb or 0),
                 self.RECHARGE_MONEY_YB, int(money_num or 0),
                 1 if is_calc else 0, str(recharge_type),
                 str(platform_type or ''), str(recharge_state),
                 str(order_id or ''), int(create_ms), str(server_id or ''),
                 str(user_guid or '')))
            self.db.commit()
            return record_id

    def recharge_check_order_repeat(self, order_id):
        """True when a live/success row already carries this order id.

        checkRechageOrderIdIsRepeat verbatim: order_id match with
        recharge_state <= '1' blocks ('0' granted and '1' pending),
        while revoked ('9') and failed (100x) rows do not.
        """
        with self.lock:
            row = self.db.execute(
                'SELECT 1 FROM recharge_record'
                ' WHERE order_id=? AND recharge_state <= ? LIMIT 1',
                (str(order_id or ''), '1')).fetchone()
            return row is not None

    def recharge_charge_total(self, role_id):
        """Lifetime YB total for a role (getChargeTotal).

        Sums money_num over the account's server-scoped success
        rows (recharge_type 3/4 excluded, state '0' only); 0 when
        the role is unknown.
        """
        with self.lock:
            role = self._recharge_role(role_id)
            if role is None:
                return 0
            user_guid, server_id = self._recharge_role_scope(dict(role))
            row = self.db.execute(
                'SELECT COALESCE(SUM(money_num),0) AS total'
                ' FROM recharge_record'
                " WHERE user_guid=? AND server_id=? AND money_type=?"
                " AND recharge_type NOT IN ('3','4')"
                ' AND recharge_state <= ?',
                (user_guid, server_id, self.RECHARGE_MONEY_YB,
                 '0')).fetchone()
            try:
                return int((dict(row) if row else {}).get('total') or 0)
            except (TypeError, ValueError):
                return 0

    def recharge_charge_total_in_time(self, role_id, start_ms, end_ms):
        """Windowed YB total for a role (getChargeTotalInTime).

        Same success shape but state <= '1' (pending offline orders
        count) with inclusive create_time bounds; a None bound is
        unbounded like the jar's isNotNull time arms.
        """
        with self.lock:
            role = self._recharge_role(role_id)
            if role is None:
                return 0
            user_guid, server_id = self._recharge_role_scope(dict(role))
            query = ('SELECT COALESCE(SUM(money_num),0) AS total'
                     ' FROM recharge_record'
                     ' WHERE user_guid=? AND server_id=? AND money_type=?'
                     " AND recharge_type NOT IN ('3','4')"
                     ' AND recharge_state <= ?')
            params = [user_guid, server_id, self.RECHARGE_MONEY_YB, '1']
            if start_ms is not None:
                query += ' AND create_time >= ?'
                params.append(int(start_ms))
            if end_ms is not None:
                query += ' AND create_time <= ?'
                params.append(int(end_ms))
            row = self.db.execute(query, params).fetchone()
            try:
                return int((dict(row) if row else {}).get('total') or 0)
            except (TypeError, ValueError):
                return 0

    def recharge_pending(self, role_id):
        """Pending-grant rows for a role (finishRecharge's login list).

        getEnableRecharges(roleId) verbatim: exact state '1',
        oldest first; the caller grants each row then marks it.
        """
        with self.lock:
            rows = self.db.execute(
                'SELECT id, user_role_id, rmb, money_type, money_num,'
                ' is_calc, recharge_type, platform_type, recharge_state,'
                ' order_id, create_time, server_id, user_guid'
                ' FROM recharge_record'
                " WHERE user_role_id=? AND recharge_state='1'"
                ' ORDER BY create_time ASC, rowid ASC',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def recharge_mark_state(self, record_id, state):
        """Move one row to a new state ('0' granted, '9' revoked)."""
        with self.lock:
            cur = self.db.execute(
                'UPDATE recharge_record SET recharge_state=? WHERE id=?',
                (str(state), str(record_id)))
            self.db.commit()
            return cur.rowcount == 1

    # MoneyType intTypes (MoneyType clinit: YXB 1, YB 2, BIND_YB 3).
    RECHARGE_MONEY_YXB = 1
    RECHARGE_MONEY_BIND_YB = 3

    @staticmethod
    def recharge_cal_yb(rmb):
        """MoneyUtil.calYb stand-in: ceil(rmb * 10).

        The gamerule util bytecode was not recovered; 1 RMB = 10 YB
        is the standard rate, isolated here so it is one edit to fix.
        """
        try:
            return max(0, int(math.ceil(float(rmb or 0) * 10)))
        except (TypeError, ValueError):
            return 0

    def recharge_grant_save_tx(self, server_id, user_guid, role_id,
                               order_id, rmb, money_num, is_calc,
                               platform_type, recharge_type,
                               create_ms=None):
        """Atomic grant-on-save: dup-guarded insert plus YB credit.

        saveRechargetYb's online arm in one commit: when a live row
        already carries the order id the insert is skipped and None
        returns (the caller answers 1004); otherwise a state-'0' row
        lands and lingshi grows by money_num. A vanished role aborts
        the whole apply (HuodongAbort, no partial row).
        """
        if create_ms is None:
            create_ms = int(time.time() * 1000)
        with self.lock:
            try:
                dupe = self.db.execute(
                    'SELECT 1 FROM recharge_record'
                    ' WHERE order_id=? AND recharge_state <= ? LIMIT 1',
                    (str(order_id or ''), '1')).fetchone()
                if dupe is not None:
                    return None
                record_id = uuid.uuid4().hex
                self.db.execute(
                    'INSERT INTO recharge_record(id, user_role_id, rmb,'
                    ' money_type, money_num, is_calc, recharge_type,'
                    ' platform_type, recharge_state, order_id,'
                    ' create_time, server_id, user_guid)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (record_id, str(role_id), float(rmb or 0),
                     self.RECHARGE_MONEY_YB, int(money_num or 0),
                     1 if is_calc else 0, str(recharge_type),
                     str(platform_type or ''), '0',
                     str(order_id or ''), int(create_ms),
                     str(server_id or ''), str(user_guid or '')))
                cur = self.db.execute(
                    'UPDATE characters'
                    ' SET lingshi = COALESCE(lingshi,0) + ?'
                    ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                    (int(money_num or 0), str(role_id),
                     str(role_id)))
                if cur.rowcount == 0:
                    raise Store.HuodongAbort('no_role')
                self.db.commit()
                return record_id
            except Exception:
                self.db.rollback()
                raise

    def recharge_finish_tx(self, role_id):
        """Atomic finishRecharge: grant every pending row, mark '0'.

        The login arm in one commit: pending (exact state '1') rows
        oldest first, each re-fetched by order/guid/server like
        getEnableRecharge (surviving duplicates are deleted, the
        first is granted once), credited by money type (YB 2 goes
        to lingshi, YXB 1 to tongqian, BIND_YB 3 to
        bind_lingshi), then flipped to '0'. Unknown money types
        and non-positive amounts stay pending. Returns the granted
        row dicts with credit_col/credit_num for the 12301 gate
        and the event fan-out; a second call grants nothing.
        """
        columns = {self.RECHARGE_MONEY_YB: 'lingshi',
                   self.RECHARGE_MONEY_YXB: 'tongqian',
                   self.RECHARGE_MONEY_BIND_YB: 'bind_lingshi'}
        with self.lock:
            try:
                pending = self.db.execute(
                    'SELECT id, user_role_id, rmb, money_type, money_num,'
                    ' is_calc, recharge_type, platform_type,'
                    ' recharge_state, order_id, create_time, server_id,'
                    ' user_guid'
                    ' FROM recharge_record'
                    " WHERE user_role_id=? AND recharge_state='1'"
                    ' ORDER BY create_time ASC, rowid ASC',
                    (str(role_id),)).fetchall()
                granted = []
                for prow in pending:
                    row = dict(prow)
                    try:
                        amount = int(row.get('money_num') or 0)
                    except (TypeError, ValueError):
                        continue
                    try:
                        mtype = int(row.get('money_type') or 0)
                    except (TypeError, ValueError):
                        continue
                    column = columns.get(mtype)
                    if column is None or amount <= 0:
                        continue
                    sibs = self.db.execute(
                        'SELECT id FROM recharge_record'
                        ' WHERE order_id=? AND user_guid=? AND server_id=?'
                        " AND recharge_state='1'"
                        ' ORDER BY create_time ASC, rowid ASC',
                        (str(row.get('order_id') or ''),
                         str(row.get('user_guid') or ''),
                         str(row.get('server_id') or ''))).fetchall()
                    sib_ids = [str(s['id']) for s in sibs]
                    if not sib_ids or str(row['id']) != sib_ids[0]:
                        if str(row['id']) in sib_ids:
                            self.db.execute(
                                'DELETE FROM recharge_record WHERE id=?',
                                (str(row['id']),))
                        continue
                    for extra in sib_ids[1:]:
                        self.db.execute(
                            'DELETE FROM recharge_record WHERE id=?',
                            (extra,))
                    cur = self.db.execute(
                        'UPDATE characters SET ' + column +
                        ' = COALESCE(' + column + ',0) + ?'
                        ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                        (amount, str(role_id), str(role_id)))
                    if cur.rowcount == 0:
                        raise Store.HuodongAbort('no_role')
                    self.db.execute(
                        "UPDATE recharge_record SET recharge_state='0'"
                        ' WHERE id=?',
                        (str(row['id']),))
                    row['recharge_state'] = '0'
                    row['credit_col'] = column
                    row['credit_num'] = amount
                    granted.append(row)
                self.db.commit()
                return granted
            except Exception:
                self.db.rollback()
                raise

    def recharge_charge_today(self, role_id, now_ms=None):
        """Today's success total for a role (getChargeToday).

        Same success shape as the lifetime total, restricted to
        rows whose create_time falls in the server-local day
        containing now_ms (DatatimeUtil.dayIsToday verbatim).
        """
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        try:
            day_start = int(_local_day_start_ms(int(now_ms)))
        except (TypeError, ValueError):
            return 0
        with self.lock:
            role = self._recharge_role(role_id)
            if role is None:
                return 0
            user_guid, server_id = self._recharge_role_scope(dict(role))
            row = self.db.execute(
                'SELECT COALESCE(SUM(money_num),0) AS total'
                ' FROM recharge_record'
                ' WHERE user_guid=? AND server_id=? AND money_type=?'
                " AND recharge_type NOT IN ('3','4')"
                " AND recharge_state='0' AND create_time >= ?",
                (user_guid, server_id, self.RECHARGE_MONEY_YB,
                 day_start)).fetchone()
            try:
                return int((dict(row) if row else {}).get('total') or 0)
            except (TypeError, ValueError):
                return 0

    def yb_consume_tx(self, role_id, amount, act_ids):
        """Atomic YB debit plus per-activity consumption accounting.

        The decrYb listener half in one commit: lingshi must cover
        the amount (False with no writes when short), then each
        live YB_CONSUME activity id in act_ids gains +amount on
        the role_huodong pay_yb map. True once committed.
        """
        try:
            debit = int(amount or 0)
        except (TypeError, ValueError):
            return False
        if debit <= 0 or not act_ids:
            return False
        with self.lock:
            try:
                row = self.db.execute(
                    'SELECT lingshi FROM characters'
                    ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                    (str(role_id), str(role_id))).fetchone()
                if row is None:
                    return False
                try:
                    have = int(dict(row).get('lingshi') or 0)
                except (TypeError, ValueError):
                    have = 0
                if have < debit:
                    return False
                self.db.execute(
                    'UPDATE characters'
                    ' SET lingshi = COALESCE(lingshi,0) - ?'
                    ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                    (debit, str(role_id), str(role_id)))
                cur = self.db.execute(
                    'SELECT pay_yb FROM role_huodong WHERE role_id=?',
                    (str(role_id),)).fetchone()
                pay_text = (dict(cur).get('pay_yb')
                            if cur else None)
                bumped = self._huodong_bump_json_multi(
                    pay_text, [str(a) for a in act_ids or []], debit)
                self.db.execute(
                    'INSERT INTO role_huodong(role_id, pay_yb)'
                    ' VALUES(?,?) ON CONFLICT(role_id) DO UPDATE'
                    ' SET pay_yb=excluded.pay_yb',
                    (str(role_id), bumped))
                self.db.commit()
                return True
            except Exception:
                self.db.rollback()
                raise

    class HuodongAbort(Exception):
        """A transactional claim/buy failed validation mid-apply."""

    @staticmethod
    def _huodong_bump_json(cur_text, key, delta=1):
        """setValue +delta: counter JSON with the key incremented."""
        try:
            counters = json.loads(cur_text or '{}')
        except (TypeError, ValueError):
            counters = {}
        if not isinstance(counters, dict):
            counters = {}
        try:
            counters[str(key)] = int(counters.get(str(key)) or 0) + delta
        except (TypeError, ValueError):
            counters[str(key)] = delta
        return json.dumps(counters)

    @classmethod
    def _huodong_consume_json(cls, cur_pay_text, yb_cost, consume_acts):
        """pay_yb JSON with one YB debit accounted, or the stored text.

        decrYb's in-tx arm: only the lingshi debit counts — yxb
        and goods costs are the carved-out exclusion — and empty
        acts or a zero cost leave the ledger untouched.
        """
        try:
            debit = int(yb_cost or 0)
        except (TypeError, ValueError):
            debit = 0
        if debit <= 0 or not consume_acts:
            return cur_pay_text if cur_pay_text is not None else '{}'
        return cls._huodong_bump_json_multi(
            cur_pay_text, [str(a) for a in consume_acts], debit)

    @classmethod
    def _huodong_bump_json_multi(cls, cur_text, keys, delta):
        """setValue +delta applied to every key (decrYb payYb arm)."""
        try:
            out = json.loads(cur_text or '{}')
        except (TypeError, ValueError):
            out = {}
        if not isinstance(out, dict):
            out = {}
        try:
            bump = int(delta or 0)
        except (TypeError, ValueError):
            bump = 0
        for key in keys or []:
            try:
                out[str(key)] = int(out.get(str(key)) or 0) + bump
            except (TypeError, ValueError):
                out[str(key)] = bump
        return json.dumps(out)

    def _huodong_tx_decr(self, role_id, goods):
        """Shrink/clear bag slots for [(goods_id, count, bind)] exactly.

        Bind-exact like the display-side affordability check; raises
        HuodongAbort when any cost is not covered, leaving stock
        untouched (checked before the first write).
        """
        matches = []
        for gid, count, bind in goods:
            rows = self.db.execute(
                'SELECT slot_num, count FROM role_bag_slot'
                ' WHERE role_id=? AND goods_id=? AND COALESCE(bind,0)=?'
                ' ORDER BY slot_num',
                (str(role_id), str(gid), int(bind or 0))).fetchall()
            have = sum(int(r['count'] or 0) for r in rows)
            if have < int(count or 0):
                raise Store.HuodongAbort(str(gid))
            matches.append((rows, int(count or 0)))
        for rows, need in matches:
            left = need
            for r in rows:
                if left <= 0:
                    break
                take = min(int(r['count'] or 0), left)
                rest = int(r['count'] or 0) - take
                if rest > 0:
                    self.db.execute(
                        'UPDATE role_bag_slot SET count=?'
                        ' WHERE role_id=? AND slot_num=?',
                        (rest, str(role_id), r['slot_num']))
                else:
                    self.db.execute(
                        'DELETE FROM role_bag_slot'
                        ' WHERE role_id=? AND slot_num=?',
                        (str(role_id), r['slot_num']))
                left -= take

    def _huodong_tx_grant(self, role_id, goods, stacks, capacity):
        """Stack then fill empty slots; HuodongAbort when short of room."""
        rows = self.db.execute(
            'SELECT slot_num, goods_id, bind, count FROM role_bag_slot'
            ' WHERE role_id=? AND slot_num>=1 AND slot_num<=?',
            (str(role_id), int(capacity or 0))).fetchall()
        by_slot = {int(r['slot_num']): dict(r) for r in rows}
        for item in goods:
            left = int(item.get('count') or 0)
            if left <= 0:
                continue
            stack = int((stacks or {}).get(str(item.get('goods_id'))) or 0)
            if stack <= 0:
                stack = 1
            gid = str(item.get('goods_id'))
            bind = int(item.get('bind') or 0)
            for num in sorted(by_slot):
                if left <= 0:
                    break
                s = by_slot[num]
                if str(s.get('goods_id')) != gid or \
                        int(s.get('bind') or 0) != bind:
                    continue
                room = stack - int(s.get('count') or 0)
                if room <= 0:
                    continue
                take = min(room, left)
                new_count = int(s.get('count') or 0) + take
                self.db.execute(
                    'UPDATE role_bag_slot SET count=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (new_count, str(role_id), num))
                s['count'] = new_count
                left -= take
            num = 1
            while left > 0 and num <= int(capacity or 0):
                if num not in by_slot:
                    take = min(stack, left)
                    self.db.execute(
                        'INSERT INTO role_bag_slot(role_id, slot_num, bag_id,'
                        ' goods_id, count, bind)'
                        ' VALUES(?,?,?,?,?,?)',
                        (str(role_id), num,
                         f'py{uuid.uuid4().hex[:16]}', gid, take, bind))
                    by_slot[num] = {'slot_num': num, 'goods_id': gid,
                                    'count': take, 'bind': bind}
                    left -= take
                num += 1
            if left > 0:
                raise Store.HuodongAbort('bag_full')

    def _huodong_tx_state(self, role_id, debits, credits):
        """Apply currency deltas from the fresh in-tx row.

        HuodongAbort when a debit is short. Credits are increments
        on top of the freshly read balance (the jar's incr
        semantics), never absolute assignments, so concurrent
        grants cannot clobber each other; debited columns ride as
        further deltas on the debited base.
        """
        row = self.db.execute(
            'SELECT lingshi, tongqian, bind_lingshi, zhenqi, exp, level,'
            ' max_hp, max_mp FROM characters WHERE CAST(id AS TEXT)=?'
            ' OR legacy_id=?',
            (str(role_id), str(role_id))).fetchone()
        if row is None:
            raise Store.HuodongAbort('no_role')
        cur = dict(row)
        fields = {}
        for col, cost in (debits or {}).items():
            try:
                have = int(cur.get(col) or 0)
            except (TypeError, ValueError):
                have = 0
            if have < int(cost or 0):
                raise Store.HuodongAbort(col)
            fields[col] = have - int(cost or 0)
        for col, val in (credits or {}).items():
            try:
                delta = int(val or 0)
            except (TypeError, ValueError):
                delta = 0
            if col in fields:
                fields[col] += delta
            else:
                try:
                    base = int(cur.get(col) or 0)
                except (TypeError, ValueError):
                    base = 0
                fields[col] = base + delta
        if fields:
            self.db.execute(
                'UPDATE characters SET ' +
                ', '.join(f'{c}=?' for c in fields) +
                ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                [*fields.values(), str(role_id), str(role_id)])

    def huodong_exchange_tx(self, role_id, yb_cost, yxb_cost,
                            decr_goods, grant_goods, stacks, capacity,
                            grant_state, day_key, max_key, exp_apply=None,
                            consume_acts=None):
        """Atomic exchange-claim apply: debit, grant, counters, consume.

        Single commit; any shortfall rolls everything back via
        HuodongAbort (the caller maps it to the jar's [0, 792001]).
        grant_state maps currency columns to increments applied to
        the fresh in-tx balances. exp_apply is None or a pure
        fn(level, exp) -> (fields, gained) run against the fresh
        in-tx character row, so simultaneous exp-granting claims
        serialize on value instead of clobbering each other with
        stale precomputed fields. consume_acts lists live
        YB_CONSUME activity ids: a positive yb_cost bumps each
        one's payYb in the same commit (decrYb), so a later abort
        reverts debit and totals together. Returns (True, exp_out)
        with exp_out None, or the exact post-commit {old_level,
        level, exp, gained} the reply frames are built from.
        """
        with self.lock:
            try:
                self._huodong_tx_decr(role_id, decr_goods or [])
                debits = {}
                if int(yb_cost or 0):
                    debits['lingshi'] = int(yb_cost)
                if int(yxb_cost or 0):
                    debits['tongqian'] = int(yxb_cost)
                self._huodong_tx_state(role_id, debits, grant_state or {})
                exp_out = None
                if exp_apply is not None:
                    erow = self.db.execute(
                        'SELECT level, exp FROM characters'
                        ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                        (str(role_id), str(role_id))).fetchone()
                    if erow is None:
                        raise Store.HuodongAbort('no_role')
                    try:
                        old_level = int(dict(erow).get('level') or 0)
                    except (TypeError, ValueError):
                        old_level = 0
                    try:
                        old_exp = int(dict(erow).get('exp') or 0)
                    except (TypeError, ValueError):
                        old_exp = 0
                    fields, gained = exp_apply(old_level, old_exp)
                    if fields:
                        self.db.execute(
                            'UPDATE characters SET ' +
                            ', '.join(f'{c}=?' for c in fields) +
                            ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                            [*fields.values(), str(role_id),
                             str(role_id)])
                    exp_out = {
                        'old_level': old_level,
                        'level': fields.get('level', old_level)
                        if isinstance(fields, dict) else old_level,
                        'exp': fields.get('exp', old_exp)
                        if isinstance(fields, dict) else old_exp,
                        'gained': bool(gained),
                    }
                self._huodong_tx_grant(role_id, grant_goods or [],
                                       stacks or {}, capacity)
                cur = self.db.execute(
                    'SELECT day_count, max_count, pay_yb'
                    ' FROM role_huodong WHERE role_id=?',
                    (str(role_id),)).fetchone()
                cur = dict(cur) if cur else {}
                day_json = self._huodong_bump_json(
                    cur.get('day_count'), day_key)
                max_json = self._huodong_bump_json(
                    cur.get('max_count'), max_key)
                pay_json = self._huodong_consume_json(
                    cur.get('pay_yb'), yb_cost, consume_acts)
                self.db.execute(
                    'INSERT INTO role_huodong(role_id, day_count,'
                    ' max_count, pay_yb)'
                    ' VALUES(?,?,?,?) ON CONFLICT(role_id) DO UPDATE'
                    ' SET day_count=excluded.day_count,'
                    ' max_count=excluded.max_count,'
                    ' pay_yb=excluded.pay_yb',
                    (str(role_id), day_json, max_json, pay_json))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            return True, exp_out

    def huodong_mall_buy_tx(self, role_id, yb_cost, grant_main,
                            grant_gifts, stacks, capacity, grant_state,
                            day_key, max_key, mall_buy_add, sell_id,
                            sell_key, sell_add, sell_max,
                            consume_acts=None):
        """Atomic mall-buy apply: debit, grants, counters, sell count.

        checkAndUpdateMallSellCount semantics: HuodongAbort when
        count overshoots maxSell minus units already sold. Like
        the exchange tx, a positive yb_cost bumps each live
        consume_acts activity's payYb in the same commit, so an
        abort reverts debit and totals together.
        """
        with self.lock:
            try:
                row = self.db.execute(
                    'SELECT mall_sell_info FROM huodong_info'
                    ' WHERE huodong_id=?',
                    (str(sell_id),)).fetchone()
                try:
                    sold_map = json.loads(
                        (dict(row).get('mall_sell_info') if row else '')
                        or '{}')
                except (TypeError, ValueError):
                    sold_map = {}
                if not isinstance(sold_map, dict):
                    sold_map = {}
                try:
                    sold = int(sold_map.get(str(sell_key)) or 0)
                except (TypeError, ValueError):
                    sold = 0
                if int(sell_add or 0) > int(sell_max or 0) - sold:
                    raise Store.HuodongAbort('sell_out')
                sold_map[str(sell_key)] = sold + int(sell_add or 0)
                self.db.execute(
                    'INSERT INTO huodong_info(huodong_id, mall_sell_info)'
                    ' VALUES(?,?) ON CONFLICT(huodong_id) DO UPDATE SET'
                    ' mall_sell_info=excluded.mall_sell_info',
                    (str(sell_id), json.dumps(sold_map)))
                self._huodong_tx_state(
                    role_id, {'lingshi': int(yb_cost or 0)},
                    grant_state or {})
                self._huodong_tx_grant(role_id, grant_gifts or [],
                                       stacks or {}, capacity)
                self._huodong_tx_grant(role_id, [grant_main],
                                       stacks or {}, capacity)
                cur = self.db.execute(
                    'SELECT day_count, max_count, mall_buy_count, pay_yb'
                    ' FROM role_huodong WHERE role_id=?',
                    (str(role_id),)).fetchone()
                cur = dict(cur) if cur else {}
                day_json = self._huodong_bump_json(
                    cur.get('day_count'), day_key)
                max_json = self._huodong_bump_json(
                    cur.get('max_count'), max_key)
                try:
                    mall_map = json.loads(
                        cur.get('mall_buy_count') or '{}')
                except (TypeError, ValueError):
                    mall_map = {}
                if not isinstance(mall_map, dict):
                    mall_map = {}
                for key, add in (mall_buy_add or {}).items():
                    try:
                        mall_map[str(key)] = \
                            int(mall_map.get(str(key)) or 0) + int(add)
                    except (TypeError, ValueError):
                        mall_map[str(key)] = int(add)
                pay_json = self._huodong_consume_json(
                    cur.get('pay_yb'), yb_cost, consume_acts)
                self.db.execute(
                    'INSERT INTO role_huodong(role_id, day_count, max_count,'
                    ' mall_buy_count, pay_yb) VALUES(?,?,?,?,?)'
                    ' ON CONFLICT(role_id) DO UPDATE SET'
                    ' day_count=excluded.day_count,'
                    ' max_count=excluded.max_count,'
                    ' mall_buy_count=excluded.mall_buy_count,'
                    ' pay_yb=excluded.pay_yb',
                    (str(role_id), day_json, max_json,
                     json.dumps(mall_map), pay_json))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            return True

    def get_guild_id(self, role_id):
        """A role's guild id, or None (getGuildInfoByRoleId null branch)."""
        with self.lock:
            row = self.db.execute(
                'SELECT guild_id FROM guild_member WHERE role_id=?',
                (str(role_id),)).fetchone()
            return row['guild_id'] if row else None

    def save_guild_member(self, role_id, guild_id, position=3):
        """Record guild membership (position defaults to member)."""
        with self.lock:
            now = int(time.time() * 1000)
            self.db.execute(
                'INSERT INTO guild_member(role_id, guild_id, position,'
                ' gongxian, gongxian_sum, create_time, update_time)'
                ' VALUES(?,?,?,?,?, ?, ?)'
                ' ON CONFLICT(role_id) DO UPDATE'
                ' SET guild_id=excluded.guild_id, position=excluded.position,'
                ' update_time=excluded.update_time',
                (str(role_id), str(guild_id), int(position or 0), 0, 0,
                 now, now))
            self.db.commit()
            return True

    def add_guild_gongxian(self, role_id, delta):
        """Accumulate contribution (addRoleGongxian); returns the new total."""
        with self.atomic() as db:
            row = db.execute(
                'SELECT gongxian, gongxian_sum FROM guild_member WHERE role_id=?',
                (str(role_id),)).fetchone()
            if row is None:
                return None
            try:
                total = int(row['gongxian'] or 0) + int(delta or 0)
                grand = int(row['gongxian_sum'] or 0) + int(delta or 0)
            except (TypeError, ValueError):
                total = int(delta or 0)
                grand = int(delta or 0)
            db.execute(
                'UPDATE guild_member SET gongxian=?, gongxian_sum=?,'
                ' update_time=? WHERE role_id=?',
                (total, grand, int(time.time() * 1000), str(role_id)))
            return total

    def get_guild_member(self, role_id):
        """Guild membership row for a role, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT role_id, guild_id, position, gongxian, gongxian_sum,'
                ' create_time, update_time FROM guild_member WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def delete_guild_member(self, role_id):
        """Remove a membership row; True when one existed."""
        with self.lock:
            cur = self.db.execute(
                'DELETE FROM guild_member WHERE role_id=?', (str(role_id),))
            self.db.commit()
            return cur.rowcount == 1

    def get_guild_members(self, guild_id):
        """Membership rows for a guild in join order."""
        with self.lock:
            rows = self.db.execute(
                'SELECT role_id, guild_id, position, gongxian, gongxian_sum,'
                ' create_time, update_time FROM guild_member WHERE guild_id=?'
                ' ORDER BY rowid',
                (str(guild_id),)).fetchall()
            return [dict(row) for row in rows]

    def count_guild_position(self, guild_id, position):
        """Members of a guild holding one position."""
        with self.lock:
            row = self.db.execute(
                'SELECT COUNT(*) n FROM guild_member'
                ' WHERE guild_id=? AND position=?',
                (str(guild_id), int(position))).fetchone()
            return int(row['n'] or 0)

    def save_guild(self, row):
        """Upsert a guild row dict keyed by id."""
        cols = ('id', 'name', 'banner_id', 'banner_level', 'banner_name',
                'user_role_id', 'vice_user_role_id', 'guild_message',
                'active_value', 'warn_value', 'guild_setting', 'money',
                'qinglong_count', 'baihu_count', 'zhuque_count',
                'xuanwu_count', 'fighting', 'create_time', 'update_time')
        with self.lock:
            values = [row.get(c) for c in cols]
            self.db.execute(
                f'INSERT INTO guild({",".join(cols)})'
                f' VALUES({",".join(["?"] * len(cols))})'
                ' ON CONFLICT(id) DO UPDATE SET '
                + ', '.join(f'{c}=excluded.{c}' for c in cols[1:]),
                values)
            self.db.commit()
            return True

    def get_guild(self, guild_id):
        """Guild row by id, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT * FROM guild WHERE id=?',
                (str(guild_id),)).fetchone()
            return dict(row) if row else None

    def find_guild_by_name(self, name):
        """Guild row with an exact name, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT * FROM guild WHERE name=?',
                (str(name),)).fetchone()
            return dict(row) if row else None

    def find_guild_by_banner_name(self, name):
        """Guild row with an exact banner name, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT * FROM guild WHERE banner_name=?',
                (str(name),)).fetchone()
            return dict(row) if row else None

    def list_guilds(self):
        """All guild rows in creation order."""
        with self.lock:
            rows = self.db.execute(
                'SELECT * FROM guild ORDER BY rowid').fetchall()
            return [dict(row) for row in rows]

    def search_guilds(self, text):
        """Guild rows whose name contains text (LIKE, escaped)."""
        with self.lock:
            like = '%' + str(text or '').replace('\\', '\\\\')\
                .replace('%', '\\%').replace('_', '\\_') + '%'
            rows = self.db.execute(
                "SELECT * FROM guild WHERE name LIKE ? ESCAPE '\\'"
                ' ORDER BY rowid',
                (like,)).fetchall()
            return [dict(row) for row in rows]

    def delete_guild(self, guild_id):
        """Delete a guild and its members/applies/ledger/log rows."""
        with self.atomic() as db:
            for table in ('guild_member', 'guild_apply',
                          'guild_gongxian', 'guild_info'):
                db.execute(
                    f'DELETE FROM {table} WHERE guild_id=?',
                    (str(guild_id),))
            db.execute('DELETE FROM guild WHERE id=?', (str(guild_id),))
            return True

    def add_guild_apply(self, guild_id, role_id):
        """Record a join application; False when already applied."""
        with self.lock:
            try:
                self.db.execute(
                    'INSERT INTO guild_apply(guild_id, role_id, create_time)'
                    ' VALUES(?,?,?)',
                    (str(guild_id), str(role_id),
                     int(time.time() * 1000)))
            except sqlite3.IntegrityError:
                return False
            self.db.commit()
            return True

    def has_guild_apply(self, guild_id, role_id):
        """True when a join application is pending."""
        with self.lock:
            row = self.db.execute(
                'SELECT id FROM guild_apply WHERE guild_id=? AND role_id=?',
                (str(guild_id), str(role_id))).fetchone()
            return row is not None

    def list_guild_applies(self, guild_id):
        """Pending join-application rows for a guild in request order."""
        with self.lock:
            rows = self.db.execute(
                'SELECT guild_id, role_id, create_time FROM guild_apply'
                ' WHERE guild_id=? ORDER BY rowid',
                (str(guild_id),)).fetchall()
            return [dict(row) for row in rows]

    def delete_guild_apply(self, guild_id, role_id):
        """Withdraw one join application."""
        with self.lock:
            self.db.execute(
                'DELETE FROM guild_apply WHERE guild_id=? AND role_id=?',
                (str(guild_id), str(role_id)))
            self.db.commit()
            return True

    def save_guild_gongxian(self, entry):
        """Append a guild contribution ledger entry; returns its row id."""
        cols = ('guild_id', 'role_id', 'money', 'qinglong_count',
                'baihu_count', 'zhuque_count', 'xuanwu_count',
                'create_time', 'update_time')
        with self.lock:
            cur = self.db.execute(
                f'INSERT INTO guild_gongxian({",".join(cols)})'
                f' VALUES({",".join(["?"] * len(cols))})',
                [entry.get(c, 0) for c in cols])
            self.db.commit()
            return cur.lastrowid

    def list_guild_gongxian(self, guild_id):
        """Contribution ledger entries for a guild."""
        with self.lock:
            rows = self.db.execute(
                'SELECT guild_id, role_id, money, qinglong_count, baihu_count,'
                ' zhuque_count, xuanwu_count, create_time, update_time'
                ' FROM guild_gongxian WHERE guild_id=? ORDER BY rowid',
                (str(guild_id),)).fetchall()
            return [dict(row) for row in rows]

    def delete_guild_gongxian(self, role_id):
        """Drop one role's contribution ledger rows (member exit)."""
        with self.lock:
            self.db.execute(
                'DELETE FROM guild_gongxian WHERE role_id=?',
                (str(role_id),))
            self.db.commit()
            return True

    def add_guild_info(self, guild_id, msg):
        """Append a guild log entry."""
        with self.lock:
            self.db.execute(
                'INSERT INTO guild_info(guild_id, msg, create_time)'
                ' VALUES(?,?,?)',
                (str(guild_id), str(msg or ''),
                 int(time.time() * 1000)))
            self.db.commit()
            return True

    def list_guild_info(self, guild_id):
        """Guild log entries in write order."""
        with self.lock:
            rows = self.db.execute(
                'SELECT guild_id, msg, create_time FROM guild_info'
                ' WHERE guild_id=? ORDER BY rowid',
                (str(guild_id),)).fetchall()
            return [dict(row) for row in rows]

    def get_role_skillbook_slots(self, role_id, min_slot=10001,
                                 max_slot=10056):
        """Skillbook slot rows for a role in [min_slot, max_slot]."""
        with self.lock:
            rows = self.db.execute(
                'SELECT slot_num, bag_id, goods_id, count, bind, expire_time,'
                ' rare_level, item_level, attributes FROM role_skillbook_slot'
                ' WHERE role_id=? AND slot_num>=? AND slot_num<=?'
                ' ORDER BY slot_num',
                (str(role_id), min_slot, max_slot)).fetchall()
            return [dict(row) for row in rows]

    def get_role_skillbook_slot(self, role_id, slot_num):
        """One skillbook slot row for a role, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT slot_num, bag_id, goods_id, count, bind, expire_time,'
                ' rare_level, item_level, attributes FROM role_skillbook_slot'
                ' WHERE role_id=? AND slot_num=?',
                (str(role_id), slot_num)).fetchone()
            return dict(row) if row else None

    def insert_role_skillbook_slot(self, role_id, row):
        """Insert one skillbook slot row; returns its row id."""
        bag_id = row.get('bag_id') or f'py{uuid.uuid4().hex[:16]}'
        with self.lock:
            self.db.execute(
                'INSERT INTO role_skillbook_slot(role_id, slot_num, bag_id,'
                ' goods_id, count, bind, expire_time, rare_level, item_level,'
                ' attributes) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (str(role_id), row.get('slot_num'), bag_id,
                 row.get('goods_id'), row.get('count') or 0,
                 row.get('bind') or 0, row.get('expire_time'),
                 row.get('rare_level') or 0, row.get('item_level') or 0,
                 row.get('attributes')))
            self.db.commit()
            return bag_id

    def update_role_skillbook_slot(self, role_id, slot, **fields):
        """Update known columns of one skillbook slot row."""
        known = {'slot_num', 'bag_id', 'goods_id', 'count', 'bind',
                 'expire_time', 'rare_level', 'item_level', 'attributes'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known skillbook columns')
        sets = ', '.join(f'{f}=?' for f in fields)
        with self.lock:
            cur = self.db.execute(
                f'UPDATE role_skillbook_slot SET {sets}'
                ' WHERE role_id=? AND slot_num=?',
                [*fields.values(), str(role_id), slot])
            self.db.commit()
            return cur.rowcount == 1

    def delete_role_skillbook_slot(self, role_id, slot_num):
        """Delete one skillbook slot row."""
        with self.lock:
            cur = self.db.execute(
                'DELETE FROM role_skillbook_slot'
                ' WHERE role_id=? AND slot_num=?',
                (str(role_id), slot_num))
            self.db.commit()
            return cur.rowcount == 1

    def get_role_buyback_all(self, role_id):
        """Every buyback row for a role, oldest createtime first."""
        with self.lock:
            rows = self.db.execute(
                'SELECT buyback_id, slot_num, goods_id, count, bind,'
                ' expire_time, rare_level, item_level, attributes, createtime'
                ' FROM role_bag_buyback WHERE role_id=?'
                ' ORDER BY createtime, buyback_id',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def get_role_buyback(self, role_id, buyback_id):
        """One buyback row by its id (the sold bag guid), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT buyback_id, slot_num, goods_id, count, bind,'
                ' expire_time, rare_level, item_level, attributes, createtime'
                ' FROM role_bag_buyback WHERE role_id=? AND buyback_id=?',
                (str(role_id), buyback_id)).fetchone()
            return dict(row) if row else None

    def insert_role_buyback(self, role_id, row):
        """Insert one buyback row; the id is the sold bag guid."""
        with self.lock:
            self.db.execute(
                'INSERT INTO role_bag_buyback(role_id, buyback_id, slot_num,'
                ' goods_id, count, bind, expire_time, rare_level, item_level,'
                ' attributes, createtime) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (str(role_id), row.get('buyback_id'),
                 row.get('slot_num'), row.get('goods_id'),
                 row.get('count') or 0, row.get('bind') or 0,
                 row.get('expire_time'), row.get('rare_level') or 0,
                 row.get('item_level') or 0, row.get('attributes'),
                 row.get('createtime') or 0))
            self.db.commit()
            return True

    def delete_role_buyback(self, role_id, buyback_id):
        """Delete one buyback row; True when a row was removed."""
        with self.lock:
            cur = self.db.execute(
                'DELETE FROM role_bag_buyback'
                ' WHERE role_id=? AND buyback_id=?',
                (str(role_id), buyback_id))
            self.db.commit()
            return cur.rowcount == 1

    def get_role_bag_dummy(self, role_id):
        """Bag dummy goods for a role as dicts of goods_id and goods_count."""
        with self.lock:
            rows = self.db.execute(
                'SELECT goods_id, goods_count FROM role_bag_dummy'
                ' WHERE role_id=? ORDER BY id',
                (str(role_id),)).fetchall()
            return [dict(r) for r in rows]

    def get_role_prop(self, role_id, goods_id):
        """One role_prop row by role and goods id, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT goods_id, use_start_time, use_stop_time,'
                ' surplus_value, surplus_time, use_count'
                ' FROM role_prop WHERE role_id=? AND goods_id=?',
                (str(role_id), str(goods_id))).fetchone()
            return dict(row) if row else None

    def save_role_prop(self, role_id, goods_id, **fields):
        """Upsert one role_prop row (only known columns are written)."""
        cols = ('use_start_time', 'use_stop_time', 'surplus_value',
                'surplus_time', 'use_count')
        sets = {k: v for k, v in fields.items() if k in cols}
        with self.lock:
            self.db.execute(
                'INSERT INTO role_prop(role_id, goods_id) VALUES(?,?)'
                ' ON CONFLICT(role_id, goods_id) DO NOTHING',
                (str(role_id), str(goods_id)))
            for key, val in sets.items():
                self.db.execute(
                    f'UPDATE role_prop SET {key}=?'
                    ' WHERE role_id=? AND goods_id=?',
                    (val, str(role_id), str(goods_id)))
            self.db.commit()
            return True

    def get_role_qiandao(self, role_id):
        """One role_qiandao row by role id, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT total_qiandao_count, month, month_qiandao,'
                ' total_qiandao_reward, month_qiandao_reward, week,'
                ' vip_buqian_count, qiandao_time, online_time'
                ' FROM role_qiandao WHERE role_id=?',
                (int(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_qiandao(self, role_id, **fields):
        """Upsert one role_qiandao row (only known columns are written)."""
        cols = ('total_qiandao_count', 'month', 'month_qiandao',
                'total_qiandao_reward', 'month_qiandao_reward', 'week',
                'vip_buqian_count', 'qiandao_time', 'online_time')
        sets = {k: v for k, v in fields.items() if k in cols}
        with self.lock:
            self.db.execute(
                'INSERT INTO role_qiandao(role_id) VALUES(?)'
                ' ON CONFLICT(role_id) DO NOTHING',
                (int(role_id),))
            for key, val in sets.items():
                self.db.execute(
                    f'UPDATE role_qiandao SET {key}=?'
                    ' WHERE role_id=?',
                    (val, int(role_id)))
            self.db.commit()
            return True

    def get_role_jiangli_list(self, role_id):
        """One role_jiangli_list row by role id, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT baidu_yingyin, baidu_yingyin_xiazai,'
                ' baidu_yingyin_time'
                ' FROM role_jiangli_list WHERE role_id=?',
                (int(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_jiangli_list(self, role_id, **fields):
        """Upsert one role_jiangli_list row (only known columns)."""
        cols = ('baidu_yingyin', 'baidu_yingyin_xiazai',
                'baidu_yingyin_time')
        sets = {k: v for k, v in fields.items() if k in cols}
        with self.lock:
            self.db.execute(
                'INSERT INTO role_jiangli_list(role_id) VALUES(?)'
                ' ON CONFLICT(role_id) DO NOTHING',
                (int(role_id),))
            for key, val in sets.items():
                self.db.execute(
                    f'UPDATE role_jiangli_list SET {key}=?'
                    ' WHERE role_id=?',
                    (val, int(role_id)))
            self.db.commit()
            return True

    def get_role_dengluqi(self, role_id):
        """One role_dengluqi row by role id, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT lingqu_state, lingqu_time'
                ' FROM role_dengluqi WHERE role_id=?',
                (int(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_dengluqi(self, role_id, **fields):
        """Upsert one role_dengluqi row (only known columns are written)."""
        cols = ('lingqu_state', 'lingqu_time')
        sets = {k: v for k, v in fields.items() if k in cols}
        with self.lock:
            self.db.execute(
                'INSERT INTO role_dengluqi(role_id) VALUES(?)'
                ' ON CONFLICT(role_id) DO NOTHING',
                (int(role_id),))
            for key, val in sets.items():
                self.db.execute(
                    f'UPDATE role_dengluqi SET {key}=?'
                    ' WHERE role_id=?',
                    (val, int(role_id)))
            self.db.commit()
            return True

    def get_role_online_reward(self, role_id):
        """One role_online_reward row by role id, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT month, online_time, month_online_time, refresh_time,'
                ' online_reward, is_lingqu_reward, month_bind_yb,'
                ' role_online_time'
                ' FROM role_online_reward WHERE role_id=?',
                (int(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_online_reward(self, role_id, **fields):
        """Upsert one role_online_reward row (only known columns are written)."""
        cols = ('month', 'online_time', 'month_online_time', 'refresh_time',
                'online_reward', 'is_lingqu_reward', 'month_bind_yb',
                'role_online_time')
        sets = {k: v for k, v in fields.items() if k in cols}
        with self.lock:
            self.db.execute(
                'INSERT INTO role_online_reward(role_id) VALUES(?)'
                ' ON CONFLICT(role_id) DO NOTHING',
                (int(role_id),))
            for key, val in sets.items():
                self.db.execute(
                    f'UPDATE role_online_reward SET {key}=?'
                    ' WHERE role_id=?',
                    (val, int(role_id)))
            self.db.commit()
            return True

    def get_role_husong(self, role_id):
        """One role_husong row by role id, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT mei_qi_id, husong_times, refresh_time,'
                ' dajie_cishu, dajie_time'
                ' FROM role_husong WHERE role_id=?',
                (int(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_husong(self, role_id, **fields):
        """Upsert one role_husong row (only known columns are written)."""
        cols = ('mei_qi_id', 'husong_times', 'refresh_time',
                'dajie_cishu', 'dajie_time')
        sets = {k: v for k, v in fields.items() if k in cols}
        with self.lock:
            self.db.execute(
                'INSERT INTO role_husong(role_id) VALUES(?)'
                ' ON CONFLICT(role_id) DO NOTHING',
                (int(role_id),))
            for key, val in sets.items():
                self.db.execute(
                    f'UPDATE role_husong SET {key}=?'
                    ' WHERE role_id=?',
                    (val, int(role_id)))
            self.db.commit()
            return True

    def get_role_vip_huodong_all(self, role_id):
        """Every vip event row for a role (tier plus both marks)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT vip, choujiang_state, lingqu_state'
                ' FROM role_vip_huodong WHERE role_id=?',
                (str(role_id),)).fetchall()
            return [dict(r) for r in rows]

    def get_role_vip_huodong(self, role_id, vip):
        """Vip event row for a role tier, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT choujiang_state, lingqu_state FROM role_vip_huodong'
                ' WHERE role_id=? AND vip=?',
                (str(role_id), int(vip))).fetchone()
            return dict(row) if row else None

    def save_role_vip_huodong(self, role_id, vip, **fields):
        """Upsert a role's vip event row; only known huodong columns."""
        allowed = {'choujiang_state', 'lingqu_state'}
        if not fields or set(fields) - allowed:
            raise ValueError('unknown huodong fields: '
                             f'{sorted(set(fields) - allowed)}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_vip_huodong(role_id, vip, {names})'
                f' VALUES(?,?,{placeholders})'
                f' ON CONFLICT(role_id, vip) DO UPDATE SET {updates}',
                (str(role_id), int(vip), *[int(v) for v in fields.values()]))
            self.db.commit()
            return True

    def get_role_bag_state(self, role_id):
        """Bag unlock state for a role (legacy role_bag_state subset), or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT bag_capacity, bag_slot_time, bag_update_slot_time,'
                ' storage_capacity, storage_slot_time, storage_update_slot_time'
                ' FROM role_bag_state WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_bag_state(self, role_id, **fields):
        """Upsert a role's bag unlock state (known state columns only)."""
        known = {'bag_capacity', 'bag_slot_time', 'bag_update_slot_time',
                 'storage_capacity', 'storage_slot_time',
                 'storage_update_slot_time'}
        if not fields or set(fields) - known:
            raise ValueError('state must contain known bag state fields')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_bag_state(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_meiren(self, role_id):
        """Owned-meiren rows for a role (legacy role_meiren subset)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT meiren_id, meiren_level, meiren_heti FROM role_meiren'
                ' WHERE role_id=? ORDER BY meiren_id',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_meiren(self, role_id, rows):
        """Replace a role's owned-meiren rows; rows carry id/level/heti."""
        with self.lock:
            self.db.execute('DELETE FROM role_meiren WHERE role_id=?',
                            (str(role_id),))
            for row in rows or []:
                if not row.get('meiren_id'):
                    continue
                self.db.execute(
                    'INSERT INTO role_meiren(role_id, meiren_id, meiren_level,'
                    ' meiren_heti) VALUES(?,?,?,?)',
                    (str(role_id), row.get('meiren_id'),
                     row.get('meiren_level') or 0, row.get('meiren_heti') or 0))
            self.db.commit()
            return True

    def get_role_baoshi(self, role_id):
        """Socketed-gem rows for a role (legacy role_baoshi subset)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT id, part, grid, level, fail_count, exp, update_time'
                ' FROM role_baoshi WHERE role_id=? ORDER BY part, grid',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def save_role_baoshi(self, role_id, rows):
        """Replace a role's gem rows; rows carry id/part/grid/level/exp."""
        with self.lock:
            self.db.execute('DELETE FROM role_baoshi WHERE role_id=?',
                            (str(role_id),))
            for row in rows or []:
                if not row.get('id'):
                    continue
                self.db.execute(
                    'INSERT INTO role_baoshi(role_id, id, part, grid, level,'
                    ' fail_count, exp, update_time) VALUES(?,?,?,?,?,?,?,?)',
                    (str(role_id), row.get('id'), row.get('part') or 0,
                     row.get('grid') or 0, row.get('level') or 0,
                     row.get('fail_count') or 0, row.get('exp') or 0,
                     row.get('update_time') or 0))
            self.db.commit()
            return True

    def get_role_stage(self, role_id):
        with self.lock:
            row = self.db.execute(
                'SELECT * FROM role_stage WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_role_stage(self, role_id, **fields):
        """Upsert legacy stage/live-state fields for a role."""
        if not fields or set(fields) - set(STAGE_COLUMNS):
            raise ValueError(f'unknown stage fields: {sorted(set(fields) - set(STAGE_COLUMNS))}')
        names = ', '.join(fields)
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO role_stage(role_id,{names}) VALUES(?,{placeholders}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def get_role_settings(self, role_id, account, server_id):
        """Read legacy-compatible per-role UI settings for an owned role."""
        with self.lock:
            row = self.db.execute(
                'SELECT s.quickbar_info, s.panel_config, s.ui_info, s.guaji_info '
                'FROM characters c LEFT JOIN role_settings s ON s.role_id=c.id '
                'WHERE CAST(c.id AS TEXT)=? AND c.account=? AND c.server_id=?',
                (str(role_id), account, server_id)).fetchone()
            if not row:
                return None
            result = dict(row)
            for field in ('panel_config', 'ui_info', 'guaji_info'):
                if result[field] is not None:
                    result[field] = bytes(result[field])
            return result

    def save_role_settings(self, role_id, account, server_id, **settings):
        """Update setting fields only when the role belongs to account/server."""
        allowed = {'quickbar_info', 'panel_config', 'ui_info', 'guaji_info'}
        if not settings or set(settings) - allowed:
            raise ValueError('unknown or empty role settings update')
        fields = ', '.join(f'{name}=excluded.{name}' for name in settings)
        names = ', '.join(settings)
        values = [bytes(value) if name in {'panel_config', 'ui_info', 'guaji_info'}
                  and value is not None else value
                  for name, value in settings.items()]
        with self.lock:
            row = self.db.execute(
                'SELECT id FROM characters WHERE CAST(id AS TEXT)=? AND account=? AND server_id=?',
                (str(role_id), account, server_id)).fetchone()
            if not row:
                return False
            rid = row['id']
            self.db.execute(
                f'INSERT INTO role_settings(role_id,{names}) VALUES(?,{",".join("?" for _ in values)}) '
                f'ON CONFLICT(role_id) DO UPDATE SET {fields}', [rid, *values])
            self.db.commit()
            return True

    def find_roles_by_name(self, name):
        """Characters whose name contains the query (RoleDao.getRolesLikeName)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT id, name, sex, face, level, job FROM characters'
                ' WHERE name LIKE ? ORDER BY id',
                ('%' + name + '%',)).fetchall()
            return [dict(r) for r in rows]

    def get_character(self, role_id, account, server_id):
        with self.lock:
            row = self.db.execute(
                'SELECT id, account, server_id, name, job, sex, face, level, exp,'
                ' map_id, map_x, map_y, hp, mp, max_hp, max_mp, tongqian,'
                ' bind_lingshi, lingshi, recive_yb, created FROM characters '
                'WHERE CAST(id AS TEXT)=? AND account=? AND server_id=?',
                (str(role_id), account, server_id)).fetchone()
            return dict(row) if row else None

    def get_booth(self, role_id):
        """A role's stall row, or None (BoothDao.cacheLoad)."""
        with self.lock:
            row = self.db.execute(
                'SELECT role_id, booth_name, booth_state, booth_jb, booth_yb,'
                ' booth_buy_time, created FROM booth WHERE role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_booth(self, role_id, **fields):
        """Upsert a role's stall row (known Booth columns only)."""
        known = {'booth_name', 'booth_state', 'booth_jb', 'booth_yb',
                 'booth_buy_time', 'created'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known booth columns')
        names = ', '.join(['role_id', *fields])
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO booth({names}) VALUES(?,'
                f'{placeholders}) ON CONFLICT(role_id) DO UPDATE'
                f' SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def list_booth_sells(self, role_id):
        """All stall listings of a role, slot order (BoothSellDao.cacheLoadAll)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT id, role_id, goods_id, count, slot, item_level,'
                ' rare_level, attributes, expire_time, sell_jb, sell_yb, bind,'
                ' created FROM booth_sell WHERE role_id=? ORDER BY slot',
                (str(role_id),)).fetchall()
            return [dict(row) for row in rows]

    def get_booth_sell(self, sell_id, role_id):
        """One stall listing by id scoped to its owner, or None."""
        with self.lock:
            row = self.db.execute(
                'SELECT id, role_id, goods_id, count, slot, item_level,'
                ' rare_level, attributes, expire_time, sell_jb, sell_yb, bind,'
                ' created FROM booth_sell WHERE id=? AND role_id=?',
                (str(sell_id), str(role_id))).fetchone()
            return dict(row) if row else None

    def get_booth_sell_by_slot(self, role_id, slot):
        """A role's listing at a slot number, or None (BoothIndexFilter)."""
        with self.lock:
            row = self.db.execute(
                'SELECT id, role_id, goods_id, count, slot, item_level,'
                ' rare_level, attributes, expire_time, sell_jb, sell_yb, bind,'
                ' created FROM booth_sell WHERE role_id=? AND slot=?',
                (str(role_id), slot)).fetchone()
            return dict(row) if row else None

    def save_booth_sell(self, sell):
        """Insert or replace one stall listing row by id."""
        with self.lock:
            self.db.execute(
                'INSERT INTO booth_sell(id, role_id, goods_id, count, slot,'
                ' item_level, rare_level, attributes, expire_time, sell_jb,'
                ' sell_yb, bind, created)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)'
                ' ON CONFLICT(id) DO UPDATE SET role_id=excluded.role_id,'
                ' goods_id=excluded.goods_id, count=excluded.count,'
                ' slot=excluded.slot, item_level=excluded.item_level,'
                ' rare_level=excluded.rare_level,'
                ' attributes=excluded.attributes,'
                ' expire_time=excluded.expire_time,'
                ' sell_jb=excluded.sell_jb, sell_yb=excluded.sell_yb,'
                ' bind=excluded.bind',
                (str(sell.get('id')), str(sell.get('role_id')),
                 sell.get('goods_id'), sell.get('count') or 0,
                 sell.get('slot') or 0, sell.get('item_level') or 0,
                 sell.get('rare_level') or 0, sell.get('attributes'),
                 sell.get('expire_time'), sell.get('sell_jb') or 0,
                 sell.get('sell_yb') or 0, sell.get('bind') or 0,
                 sell.get('created') or 0))
            self.db.commit()
            return True

    def delete_booth_sell(self, sell_id, role_id):
        """Delete one owner-scoped stall listing; True when a row vanished."""
        with self.lock:
            cur = self.db.execute(
                'DELETE FROM booth_sell WHERE id=? AND role_id=?',
                (str(sell_id), str(role_id)))
            self.db.commit()
            return cur.rowcount == 1

    def list_public_booths(self):
        """Stall rows holding at least one listing (in-memory BoothsData)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT b.role_id, b.booth_name, b.booth_state, b.booth_jb,'
                ' b.booth_yb, b.booth_buy_time, b.created FROM booth b'
                ' WHERE EXISTS (SELECT 1 FROM booth_sell s'
                ' WHERE s.role_id=b.role_id)'
                ' ORDER BY b.role_id').fetchall()
            return [dict(row) for row in rows]

    def list_booth_trade_logs(self, role_id):
        """A seller's trade-log codes, newest first (TradeLogComparator)."""
        with self.lock:
            rows = self.db.execute(
                'SELECT log_code FROM booth_trade_log WHERE role_id=?'
                ' ORDER BY created DESC, rowid DESC',
                (str(role_id),)).fetchall()
            return [row['log_code'] for row in rows]

    def save_booth_trade_log(self, role_id, log_type, log_code):
        """Append a seller trade log, trimming past 50 rows like Java."""
        with self.lock:
            now = int(time.time() * 1000)
            lid = f'bt{uuid.uuid4().hex[:16]}'
            self.db.execute(
                'INSERT INTO booth_trade_log(id, role_id, log_type, log_code,'
                ' created) VALUES(?,?,?,?,?)',
                (lid, str(role_id), log_type, log_code, now))
            self.db.execute(
                'DELETE FROM booth_trade_log WHERE id IN ('
                'SELECT id FROM booth_trade_log WHERE role_id=?'
                ' ORDER BY created DESC, rowid DESC LIMIT -1 OFFSET 50)',
                (str(role_id),))
            self.db.commit()
            return True

    def get_role_brief(self, role_id):
        """Cross-account identity card for stall and friend lookups."""
        with self.lock:
            row = self.db.execute(
                'SELECT id, legacy_id, name, level, exp, sex, face, job'
                ' FROM characters'
                ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                (str(role_id), str(role_id))).fetchone()
            return dict(row) if row else None

    @contextmanager
    def booth_tx(self):
        """One all-or-nothing stall mutation: BEGIN IMMEDIATE, commit/rollback."""
        with self.atomic() as db:
            yield db

    @contextmanager
    def atomic(self):
        """One all-or-nothing mutation: BEGIN IMMEDIATE, commit/rollback."""
        with self.lock:
            try:
                self.db.execute('BEGIN IMMEDIATE')
            except sqlite3.Error:
                pass
            try:
                yield self.db
            except Exception:
                try:
                    self.db.rollback()
                except sqlite3.Error:
                    pass
                raise
            try:
                self.db.commit()
            except sqlite3.Error:
                try:
                    self.db.rollback()
                except sqlite3.Error:
                    pass
                raise

    @staticmethod
    def _tx_bag_alloc(db, role_id, item, capacity):
        """Stack-or-first-free-slot plan inside a stall transaction.

        Returns ('stack', slot_num, new_count) or ('new', slot_num, count)
        or None when nothing fits. Reads only; the caller applies it."""
        rows = db.execute(
            'SELECT slot_num, goods_id, count, bind FROM role_bag_slot'
            ' WHERE role_id=? AND slot_num>=1 AND slot_num<=150',
            (str(role_id),)).fetchall()
        try:
            stack = int(item.get('stack') or 1)
        except (TypeError, ValueError):
            stack = 1
        if stack < 1:
            stack = 1
        try:
            left = int(item.get('count') or 0)
        except (TypeError, ValueError):
            return None
        if left <= 0:
            return None
        by_slot = {r['slot_num']: dict(r) for r in rows}
        for slot_num in sorted(by_slot):
            if left <= 0:
                break
            row = by_slot[slot_num]
            if str(row.get('goods_id')) != str(item.get('goods_id')):
                continue
            if (row.get('bind') or 0) != (item.get('bind') or 0):
                continue
            try:
                room = stack - int(row.get('count') or 0)
            except (TypeError, ValueError):
                room = 0
            if room > 0:
                return ('stack', slot_num, int(row.get('count') or 0) + left
                        if left <= room else int(row.get('count') or 0) + room)
        try:
            cap = int(capacity or 0)
        except (TypeError, ValueError):
            cap = 0
        for num in range(1, cap + 1):
            if num not in by_slot:
                return ('new', num, left)
        return None

    @staticmethod
    def _tx_bag_capacity(db, role_id):
        row = db.execute(
            'SELECT bag_capacity FROM role_bag_state WHERE role_id=?',
            (str(role_id),)).fetchone()
        try:
            return int((row or {}).get('bag_capacity') if row is None
                       else row['bag_capacity'] or 0)
        except (TypeError, ValueError):
            return 0

    def booth_list_goods_tx(self, sell, bag_slot_num, bag_have, bag_take):
        """List bag goods atomically: shrink the stack, insert the listing.

        Returns 'ok' or 'changed' (bag moved under us; caller reports the
        Java stale-bag error)."""
        with self.booth_tx() as db:
            row = db.execute(
                'SELECT count FROM role_bag_slot WHERE role_id=? AND slot_num=?',
                (str(sell['role_id']), bag_slot_num)).fetchone()
            if row is None or int(row['count'] or 0) != bag_have:
                return 'changed'
            if bag_take >= bag_have:
                db.execute(
                    'DELETE FROM role_bag_slot WHERE role_id=? AND slot_num=?',
                    (str(sell['role_id']), bag_slot_num))
            else:
                db.execute(
                    'UPDATE role_bag_slot SET count=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (bag_have - bag_take, str(sell['role_id']), bag_slot_num))
            db.execute(
                'INSERT INTO booth_sell(id, role_id, goods_id, count, slot,'
                ' item_level, rare_level, attributes, expire_time, sell_jb,'
                ' sell_yb, bind, created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (str(sell['id']), str(sell['role_id']), sell.get('goods_id'),
                 sell.get('count') or 0, sell.get('slot') or 0,
                 sell.get('item_level') or 0, sell.get('rare_level') or 0,
                 sell.get('attributes'), sell.get('expire_time'),
                 sell.get('sell_jb') or 0, sell.get('sell_yb') or 0,
                 sell.get('bind') or 0, sell.get('created') or 0))
            return 'ok'

    def booth_delist_goods_tx(self, sell_id, role_id, item, stack):
        """Delist atomically: drop the listing, restore goods to the bag.

        Returns 'ok', 'gone' (listing vanished), or 'full' (bag has no
        room; nothing is mutated)."""
        with self.booth_tx() as db:
            row = db.execute(
                'SELECT goods_id, count, bind FROM booth_sell'
                ' WHERE id=? AND role_id=?',
                (str(sell_id), str(role_id))).fetchone()
            if row is None:
                return 'gone'
            cap = self._tx_bag_capacity(db, role_id)
            plan = self._tx_bag_alloc(db, role_id, dict(item, stack=stack),
                                      cap)
            if plan is None:
                return 'full'
            db.execute('DELETE FROM booth_sell WHERE id=? AND role_id=?',
                       (str(sell_id), str(role_id)))
            kind, slot_num, count = plan
            if kind == 'stack':
                db.execute(
                    'UPDATE role_bag_slot SET count=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (count, str(role_id), slot_num))
            else:
                db.execute(
                    'INSERT INTO role_bag_slot(role_id, slot_num, bag_id,'
                    ' goods_id, count, bind, expire_time, rare_level,'
                    ' item_level, attributes) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (str(role_id), slot_num, f'py{uuid.uuid4().hex[:16]}',
                     item.get('goods_id'), count, item.get('bind') or 0,
                     item.get('expire_time'), item.get('rare_level') or 0,
                     item.get('item_level') or 0, item.get('attributes')))
            return 'ok'

    def booth_buy_goods_tx(self, buyer_id, pay_yxb, pay_yb, item, stack,
                           seller_id, sell_id, exp_yb, exp_jb, fee,
                           buyer_booth, seller_add_jb, seller_add_yb,
                           log_code):
        """Settle a goods purchase atomically (Java buyBoothGoods order).

        Verifies the listing (id, owner, prices) and the buyer's funds
        inside the transaction, so a competing buyer either wins cleanly
        or sees 'gone'/'changed'. Returns 'ok', 'gone', 'changed',
        'funds' or 'full'; only 'ok' mutates anything."""
        with self.booth_tx() as db:
            sell = db.execute(
                'SELECT sell_jb, sell_yb FROM booth_sell'
                ' WHERE id=? AND role_id=?',
                (str(sell_id), str(seller_id))).fetchone()
            if sell is None:
                return 'gone'
            try:
                listed_jb = int(sell['sell_jb'] or 0)
                listed_yb = int(sell['sell_yb'] or 0)
            except (TypeError, ValueError):
                return 'changed'
            if listed_jb != exp_jb or listed_yb != exp_yb:
                return 'changed'
            wallet = db.execute(
                'SELECT tongqian, lingshi FROM characters'
                ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                (str(buyer_id), str(buyer_id))).fetchone()
            if wallet is None:
                return 'funds'
            try:
                have_yxb = int(wallet['tongqian'] or 0)
                have_yb = int(wallet['lingshi'] or 0)
            except (TypeError, ValueError):
                return 'funds'
            if have_yxb < pay_yxb or have_yb < pay_yb:
                return 'funds'
            cap = self._tx_bag_capacity(db, buyer_id)
            plan = self._tx_bag_alloc(db, buyer_id, dict(item, stack=stack),
                                      cap)
            if plan is None:
                return 'full'
            db.execute('DELETE FROM booth_sell WHERE id=? AND role_id=?',
                       (str(sell_id), str(seller_id)))
            db.execute(
                'UPDATE characters SET tongqian=?, lingshi=?'
                ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                (have_yxb - pay_yxb, have_yb - pay_yb,
                 str(buyer_id), str(buyer_id)))
            kind, slot_num, count = plan
            if kind == 'stack':
                db.execute(
                    'UPDATE role_bag_slot SET count=?'
                    ' WHERE role_id=? AND slot_num=?',
                    (count, str(buyer_id), slot_num))
            else:
                db.execute(
                    'INSERT INTO role_bag_slot(role_id, slot_num, bag_id,'
                    ' goods_id, count, bind, expire_time, rare_level,'
                    ' item_level, attributes) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (str(buyer_id), slot_num, f'py{uuid.uuid4().hex[:16]}',
                     item.get('goods_id'), count, item.get('bind') or 0,
                     item.get('expire_time'), item.get('rare_level') or 0,
                     item.get('item_level') or 0, item.get('attributes')))
            if buyer_booth.get('exists'):
                db.execute(
                    'UPDATE booth SET booth_jb=?, booth_yb=? WHERE role_id=?',
                    (buyer_booth.get('jb') or 0, buyer_booth.get('yb') or 0,
                     str(buyer_id)))
            else:
                db.execute(
                    'INSERT INTO booth(role_id, booth_name, booth_state,'
                    ' booth_jb, booth_yb, booth_buy_time, created)'
                    ' VALUES(?,?,1,?,?,?,?)',
                    (str(buyer_id), None, buyer_booth.get('jb') or 0,
                     buyer_booth.get('yb') or 0,
                     buyer_booth.get('buy_time'),
                     buyer_booth.get('created') or 0))
            db.execute(
                'UPDATE booth SET booth_jb=booth_jb+?, booth_yb=booth_yb+?'
                ' WHERE role_id=?',
                (seller_add_jb, seller_add_yb, str(seller_id)))
            self._tx_trade_log(db, seller_id, 3, log_code)
            return 'ok'

    def booth_money_position_tx(self, role_id, money_col, expect_id,
                                take, give, sell):
        """Open/resize/close a money-market listing atomically.

        take/give move character funds; sell None deletes the expect_id
        row, a sell dict inserts/updates it. Returns 'ok', 'funds' or
        'gone'."""
        with self.booth_tx() as db:
            wallet = db.execute(
                f'SELECT {money_col} FROM characters'
                ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                (str(role_id), str(role_id))).fetchone()
            if wallet is None:
                return 'funds'
            try:
                have = int(wallet[money_col] or 0)
            except (TypeError, ValueError):
                return 'funds'
            if have < take:
                return 'funds'
            if expect_id is not None:
                row = db.execute(
                    'SELECT id FROM booth_sell WHERE id=? AND role_id=?',
                    (str(expect_id), str(role_id))).fetchone()
                if row is None:
                    return 'gone'
            if take:
                db.execute(
                    f'UPDATE characters SET {money_col}={money_col}-?'
                    ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                    (take, str(role_id), str(role_id)))
            if give:
                db.execute(
                    f'UPDATE characters SET {money_col}={money_col}+?'
                    ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                    (give, str(role_id), str(role_id)))
            if sell is None:
                db.execute('DELETE FROM booth_sell WHERE id=? AND role_id=?',
                           (str(expect_id), str(role_id)))
            elif expect_id is None:
                clash = db.execute(
                    'SELECT id FROM booth_sell WHERE role_id=? AND slot=?',
                    (str(role_id), sell.get('slot') or 0)).fetchone()
                if clash is not None:
                    return 'changed'
                db.execute(
                    'INSERT INTO booth_sell(id, role_id, goods_id, count,'
                    ' slot, item_level, rare_level, attributes, expire_time,'
                    ' sell_jb, sell_yb, bind, created)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (str(sell['id']), str(role_id), sell.get('goods_id'),
                     1, sell.get('slot') or 0, 0, 0, None, 0,
                     sell.get('sell_jb') or 0, sell.get('sell_yb') or 0,
                     0, sell.get('created') or 0))
            else:
                db.execute(
                    'UPDATE booth_sell SET sell_jb=?, sell_yb=?'
                    ' WHERE id=? AND role_id=?',
                    (sell.get('sell_jb') or 0, sell.get('sell_yb') or 0,
                     str(expect_id), str(role_id)))
            return 'ok'

    def booth_money_buy_tx(self, buyer_id, pay_col, pay_amount, get_jb,
                           get_yb, seller_id, slot, exp_first, exp_second,
                           yb_type, fee, log_code):
        """Settle a money-market purchase atomically.

        Returns 'ok', 'gone' (no listing), 'changed' (prices moved),
        or 'funds'. Only 'ok' mutates anything."""
        with self.booth_tx() as db:
            sell = db.execute(
                'SELECT id, sell_jb, sell_yb FROM booth_sell'
                ' WHERE role_id=? AND slot=?',
                (str(seller_id), slot)).fetchone()
            if sell is None:
                return 'gone'
            try:
                if yb_type:
                    listed_first = int(sell['sell_yb'] or 0)
                    listed_second = int(sell['sell_jb'] or 0)
                else:
                    listed_first = int(sell['sell_jb'] or 0)
                    listed_second = int(sell['sell_yb'] or 0)
            except (TypeError, ValueError):
                return 'changed'
            if listed_first != exp_first or listed_second != exp_second:
                return 'changed'
            wallet = db.execute(
                f'SELECT {pay_col} FROM characters'
                ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                (str(buyer_id), str(buyer_id))).fetchone()
            if wallet is None:
                return 'funds'
            try:
                have = int(wallet[pay_col] or 0)
            except (TypeError, ValueError):
                return 'funds'
            if have < pay_amount:
                return 'funds'
            db.execute(
                f'UPDATE characters SET {pay_col}={pay_col}-?'
                ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                (pay_amount, str(buyer_id), str(buyer_id)))
            db.execute('DELETE FROM booth_sell WHERE id=?', (sell['id'],))
            buyer = db.execute(
                'SELECT booth_jb, booth_yb FROM booth WHERE role_id=?',
                (str(buyer_id),)).fetchone()
            if buyer is None:
                db.execute(
                    'INSERT INTO booth(role_id, booth_name, booth_state,'
                    ' booth_jb, booth_yb, booth_buy_time, created)'
                    ' VALUES(?,?,1,?,?,?,?)',
                    (str(buyer_id), None, get_jb, get_yb,
                     int(time.time() * 1000),
                     int(time.time() * 1000)))
                new_buyer = (get_jb, get_yb)
            else:
                try:
                    bj = int(buyer['booth_jb'] or 0) + get_jb
                    by = int(buyer['booth_yb'] or 0) + get_yb
                except (TypeError, ValueError):
                    bj, by = get_jb, get_yb
                db.execute(
                    'UPDATE booth SET booth_jb=?, booth_yb=? WHERE role_id=?',
                    (bj, by, str(buyer_id)))
                new_buyer = (bj, by)
            if yb_type:
                db.execute(
                    'UPDATE booth SET booth_jb=booth_jb+? WHERE role_id=?',
                    (pay_amount, str(seller_id)))
            else:
                db.execute(
                    'UPDATE booth SET booth_yb=booth_yb+? WHERE role_id=?',
                    (pay_amount - fee, str(seller_id)))
            seller = db.execute(
                'SELECT booth_jb, booth_yb FROM booth WHERE role_id=?',
                (str(seller_id),)).fetchone()
            new_seller = (int(seller['booth_jb'] or 0),
                          int(seller['booth_yb'] or 0)) \
                if seller is not None else (0, 0)
            self._tx_trade_log(db, seller_id, 2, log_code)
            return ('ok', new_buyer, new_seller)

    def booth_claim_tx(self, role_id, col_jb, col_yb):
        """Collect stall balances atomically; returns (jb, yb)."""
        with self.booth_tx() as db:
            row = db.execute(
                'SELECT booth_jb, booth_yb FROM booth WHERE role_id=?',
                (str(role_id),)).fetchone()
            if row is None:
                return (0, 0, False)
            try:
                take_jb = int(row['booth_jb'] or 0)
                take_yb = int(row['booth_yb'] or 0)
            except (TypeError, ValueError):
                take_jb, take_yb = 0, 0
            if take_jb == 0 and take_yb == 0:
                return (0, 0, True)
            if take_jb:
                db.execute(
                    f'UPDATE characters SET {col_jb}={col_jb}+?'
                    ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                    (take_jb, str(role_id), str(role_id)))
            if take_yb:
                db.execute(
                    f'UPDATE characters SET {col_yb}={col_yb}+?'
                    ' WHERE CAST(id AS TEXT)=? OR legacy_id=?',
                    (take_yb, str(role_id), str(role_id)))
            db.execute(
                'UPDATE booth SET booth_jb=0, booth_yb=0 WHERE role_id=?',
                (str(role_id),))
            return (take_jb, take_yb, True)

    @staticmethod
    def _tx_trade_log(db, role_id, log_type, log_code):
        now = int(time.time() * 1000)
        lid = f'bt{uuid.uuid4().hex[:16]}'
        db.execute(
            'INSERT INTO booth_trade_log(id, role_id, log_type, log_code,'
            ' created) VALUES(?,?,?,?,?)',
            (lid, str(role_id), log_type, log_code, now))
        db.execute(
            'DELETE FROM booth_trade_log WHERE id IN ('
            'SELECT id FROM booth_trade_log WHERE role_id=?'
            ' ORDER BY created DESC, rowid DESC LIMIT -1 OFFSET 50)',
            (str(role_id),))

    # -- friend lists (RoleFriend/RoleFoe/RoleBlacklist/RoleContacts) --
    _FRIEND_TABLES = {
        'friend': ('role_friend', 'friend_id'),
        'foe': ('role_foe', 'foe_id'),
        'blacklist': ('role_blacklist', 'blacklist_id'),
        'contacts': ('role_contacts', 'contacts_id'),
    }

    def list_friend_links(self, kind, owner_id):
        """Directed links of one owner (RoleFriendDao.cacheLoadAll)."""
        table, _col = self._FRIEND_TABLES[kind]
        with self.lock:
            rows = self.db.execute(
                f'SELECT * FROM {table} WHERE user_role_id=? ORDER BY rowid',
                (str(owner_id),)).fetchall()
            return [dict(r) for r in rows]

    def has_friend_link(self, kind, owner_id, target_id):
        """Whether the directed link exists (the *IdFilter queries)."""
        table, col = self._FRIEND_TABLES[kind]
        with self.lock:
            row = self.db.execute(
                f'SELECT id FROM {table}'
                ' WHERE user_role_id=? AND '
                f'{col}=?',
                (str(owner_id), str(target_id))).fetchone()
            return row is not None

    def count_friend_links(self, kind, owner_id):
        table, _col = self._FRIEND_TABLES[kind]
        with self.lock:
            row = self.db.execute(
                f'SELECT COUNT(*) n FROM {table} WHERE user_role_id=?',
                (str(owner_id),)).fetchone()
            return int(row['n'] or 0)

    def follower_ids(self, kind, target_id):
        """Owners holding a link to the target (getFriendByFriendId etc)."""
        table, col = self._FRIEND_TABLES[kind]
        with self.lock:
            rows = self.db.execute(
                f'SELECT user_role_id FROM {table} WHERE {col}=?',
                (str(target_id),)).fetchall()
            return [r['user_role_id'] for r in rows]

    def friend_add_tx(self, kind, owner_id, target_id, cap, extra=None):
        """Add a link, evicting the oldest past the cap (Java cacheDelete).

        Returns (True, evicted_row_or_None). extra sets RoleFoe.foe_count.
        """
        table, col = self._FRIEND_TABLES[kind]
        with self.atomic() as db:
            row = db.execute(
                f'SELECT id FROM {table}'
                ' WHERE user_role_id=? AND '
                f'{col}=?',
                (str(owner_id), str(target_id))).fetchone()
            if row is not None:
                return (False, None)
            rows = db.execute(
                f'SELECT id FROM {table}'
                ' WHERE user_role_id=? ORDER BY rowid',
                (str(owner_id),)).fetchall()
            evicted = None
            if len(rows) >= cap:
                victim = rows[0]['id']
                gone = db.execute(
                    f'SELECT * FROM {table} WHERE id=?',
                    (victim,)).fetchone()
                db.execute(f'DELETE FROM {table} WHERE id=?', (victim,))
                evicted = dict(gone) if gone else {'id': victim}
            now = int(time.time() * 1000)
            lid = f'fr{uuid.uuid4().hex[:16]}'
            if kind == 'foe':
                db.execute(
                    'INSERT INTO role_foe(id, user_role_id, foe_id,'
                    ' foe_count, order_id, created)'
                    ' VALUES(?,?,?,?,?,?)',
                    (lid, str(owner_id), str(target_id),
                     extra if extra is not None else 0, 0, now))
            else:
                db.execute(
                    f'INSERT INTO {table}(id, user_role_id, {col}, created)'
                    ' VALUES(?,?,?,?)',
                    (lid, str(owner_id), str(target_id), now))
            return (True, evicted)

    def friend_del_tx(self, kind, owner_id, target_id):
        """Delete one directed link; False when it was absent."""
        table, col = self._FRIEND_TABLES[kind]
        with self.atomic() as db:
            cur = db.execute(
                f'DELETE FROM {table}'
                ' WHERE user_role_id=? AND '
                f'{col}=?',
                (str(owner_id), str(target_id)))
            return cur.rowcount > 0

    def friend_touch_foe_tx(self, owner_id, target_id, delta,
                            floor, ceil):
        """Bump a foe counter, clamped (roleFight +/-1, caps +/-999)."""
        with self.atomic() as db:
            row = db.execute(
                'SELECT foe_count FROM role_foe'
                ' WHERE user_role_id=? AND foe_id=?',
                (str(owner_id), str(target_id))).fetchone()
            if row is None:
                return None
            try:
                count = int(row['foe_count'] or 0) + delta
            except (TypeError, ValueError):
                count = delta
            count = max(floor, min(ceil, count))
            db.execute(
                'UPDATE role_foe SET foe_count=?'
                ' WHERE user_role_id=? AND foe_id=?',
                (count, str(owner_id), str(target_id)))
            return count

    def get_friend_info(self, role_id):
        """A role's headline row, or None (FriendInfoDao.dbLoad)."""
        with self.lock:
            row = self.db.execute(
                'SELECT user_role_id, xinqing, friend_count FROM friend_info'
                ' WHERE user_role_id=?',
                (str(role_id),)).fetchone()
            return dict(row) if row else None

    def save_friend_info(self, role_id, **fields):
        """Upsert a headline row (known FriendInfo columns only)."""
        known = {'xinqing', 'friend_count'}
        if not fields or set(fields) - known:
            raise ValueError('fields must contain known friend columns')
        names = ', '.join(['user_role_id', *fields])
        placeholders = ', '.join('?' for _ in fields)
        updates = ', '.join(f'{n}=excluded.{n}' for n in fields)
        with self.lock:
            self.db.execute(
                f'INSERT INTO friend_info({names}) VALUES(?,{placeholders})'
                ' ON CONFLICT(user_role_id) DO UPDATE'
                f' SET {updates}',
                [str(role_id), *fields.values()])
            self.db.commit()
            return True

    def friend_add_count_tx(self, role_id):
        """Increment the added-friend counter, creating the row (addFriends)."""
        with self.atomic() as db:
            row = db.execute(
                'SELECT friend_count FROM friend_info WHERE user_role_id=?',
                (str(role_id),)).fetchone()
            if row is None:
                db.execute(
                    'INSERT INTO friend_info(user_role_id, xinqing,'
                    ' friend_count) VALUES(?,?,1)',
                    (str(role_id), None))
                return 1
            try:
                count = int(row['friend_count'] or 0) + 1
            except (TypeError, ValueError):
                count = 1
            db.execute(
                'UPDATE friend_info SET friend_count=? WHERE user_role_id=?',
                (count, str(role_id)))
            return count
