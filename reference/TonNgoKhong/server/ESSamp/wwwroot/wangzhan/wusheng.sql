/*
Navicat MySQL Data Transfer

Source Server         : localhost_3306
Source Server Version : 50137
Source Host           : 127.0.0.1:3306
Source Database       : wusheng

Target Server Type    : MYSQL
Target Server Version : 50137
File Encoding         : 65001

Date: 2014-03-02 01:26:22
*/

SET FOREIGN_KEY_CHECKS=0;
-- ----------------------------
-- Table structure for `actstat`
-- ----------------------------
DROP TABLE IF EXISTS `actstat`;
CREATE TABLE `actstat` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `drawer` varchar(50) DEFAULT NULL COMMENT '领取者',
  `activetype` varchar(20) DEFAULT NULL COMMENT '活动类型',
  `tag` varchar(50) DEFAULT NULL COMMENT '标记',
  `info` varchar(100) DEFAULT NULL COMMENT '其他信息',
  `time` datetime DEFAULT NULL COMMENT '时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of actstat
-- ----------------------------

-- ----------------------------
-- Table structure for `bang`
-- ----------------------------
DROP TABLE IF EXISTS `bang`;
CREATE TABLE `bang` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '主键',
  `name` varchar(40) NOT NULL COMMENT '帮名',
  `level` int(11) NOT NULL COMMENT '帮派等级',
  `max` int(11) NOT NULL COMMENT '帮派人数上限',
  `busy` int(11) NOT NULL COMMENT '繁荣度',
  `qq` varchar(30) DEFAULT NULL COMMENT 'qq群号',
  `declaration` varchar(255) DEFAULT NULL COMMENT '帮派宣言',
  `notice` varchar(255) DEFAULT NULL COMMENT '帮派公告',
  `flag` varchar(255) NOT NULL COMMENT '帮派旗帜',
  `rank` int(11) NOT NULL COMMENT '帮派排名',
  `members` blob NOT NULL COMMENT '帮派成员',
  `requests` longblob NOT NULL COMMENT '申请信息',
  `bangNotes` blob NOT NULL COMMENT '帮派日志',
  `mark` int(11) NOT NULL COMMENT '一年中第几周',
  `record` blob NOT NULL COMMENT '入帮记录',
  `boss_set` int(11) NOT NULL COMMENT 'boss设置',
  `viceBoss_set` int(11) NOT NULL COMMENT '副帮主设置',
  `togetherList` blob COMMENT '齐心协力',
  `fun1` int(11) NOT NULL COMMENT '帮派活动1',
  `fun2` int(11) NOT NULL COMMENT '帮派活动2',
  `fun3` int(11) NOT NULL COMMENT '帮派活动3',
  `fun4` int(11) NOT NULL COMMENT '帮派活动4',
  `bossID` bigint(20) DEFAULT NULL,
  `change_BangBoss_Time` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of bang
-- ----------------------------

-- ----------------------------
-- Table structure for `bangwar`
-- ----------------------------
DROP TABLE IF EXISTS `bangwar`;
CREATE TABLE `bangwar` (
  `belong_bang_id` int(10) DEFAULT '-1',
  `belong_bang_name` varchar(255) DEFAULT NULL,
  `bang_occupy_time` bigint(20) NOT NULL DEFAULT '0' COMMENT '帮派占领时间',
  `bangtitle` blob NOT NULL,
  `belong_bang_boss_name` varchar(255) DEFAULT NULL,
  `bossSkin` int(10) NOT NULL DEFAULT '0' COMMENT '帮主的表皮',
  `bangwarAwardFlag` smallint(10) NOT NULL COMMENT '帮派争霸赛和守卫战奖励领取标记'
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of bangwar
-- ----------------------------

-- ----------------------------
-- Table structure for `charge`
-- ----------------------------
DROP TABLE IF EXISTS `charge`;
CREATE TABLE `charge` (
  `loginName` varchar(200) NOT NULL COMMENT '用户id',
  `charge` int(10) unsigned NOT NULL DEFAULT '0' COMMENT '充值币',
  PRIMARY KEY (`loginName`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of charge
-- ----------------------------

-- ----------------------------
-- Table structure for `email`
-- ----------------------------
DROP TABLE IF EXISTS `email`;
CREATE TABLE `email` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '自动编号',
  `playerId` bigint(20) NOT NULL COMMENT '角色id',
  `playerName` varchar(200) NOT NULL COMMENT '角色名',
  `fromplayerId` bigint(20) NOT NULL COMMENT '发件人id',
  `fromplayerName` varchar(200) NOT NULL COMMENT '发件人name',
  `emailType` smallint(1) NOT NULL COMMENT '邮件类型',
  `appendType` smallint(1) NOT NULL COMMENT '附件类型',
  `emailState` smallint(1) NOT NULL COMMENT '邮件状态',
  `title` varchar(200) DEFAULT NULL COMMENT '邮件主题',
  `message` varchar(500) DEFAULT NULL COMMENT '邮件内容',
  `fromTime` bigint(20) NOT NULL COMMENT '邮件发送时间',
  `itemId` int(11) NOT NULL,
  `item` blob NOT NULL COMMENT '道具',
  `money` int(11) NOT NULL COMMENT '金钱',
  `gold` int(11) unsigned NOT NULL COMMENT '元宝',
  `state` smallint(1) NOT NULL DEFAULT '1' COMMENT '1未删除，2删除',
  PRIMARY KEY (`id`),
  KEY `idx_playerid` (`playerId`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of email
-- ----------------------------

-- ----------------------------
-- Table structure for `emall_item`
-- ----------------------------
DROP TABLE IF EXISTS `emall_item`;
CREATE TABLE `emall_item` (
  `id` int(11) NOT NULL COMMENT '物品编号',
  `num` int(11) NOT NULL COMMENT '限购剩余个数',
  `rushTime` int(11) NOT NULL COMMENT '刷新时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of emall_item
-- ----------------------------

-- ----------------------------
-- Table structure for `friends`
-- ----------------------------
DROP TABLE IF EXISTS `friends`;
CREATE TABLE `friends` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '编号',
  `pid` bigint(20) NOT NULL COMMENT '主 人物id',
  `friendId` bigint(20) NOT NULL COMMENT '好友id 副',
  `type` int(11) NOT NULL COMMENT '好友关系类型 1：好友，2：黑名单，3：仇人',
  `value` int(11) NOT NULL COMMENT '关系值，亲密度或仇恨值',
  `time` bigint(20) NOT NULL COMMENT '改变时间',
  PRIMARY KEY (`id`),
  KEY `idx_pid` (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of friends
-- ----------------------------

-- ----------------------------
-- Table structure for `log_consume_template_month`
-- ----------------------------
DROP TABLE IF EXISTS `log_consume_template_month`;
CREATE TABLE `log_consume_template_month` (
  `player_id` bigint(20) DEFAULT NULL COMMENT '玩家唯一ID',
  `open_id` varchar(64) DEFAULT NULL COMMENT '玩家开放ID',
  `player_name` varchar(64) DEFAULT NULL COMMENT '玩家姓名',
  `bill_no` varchar(20) DEFAULT NULL COMMENT '订单号',
  `token` varchar(64) DEFAULT NULL COMMENT '令牌',
  `trade_type` int(11) DEFAULT NULL COMMENT '交易类型',
  `code_name` varchar(200) DEFAULT NULL COMMENT '调用模块',
  `is_success` int(11) DEFAULT NULL COMMENT '是否成功',
  `err_msg` varchar(2000) DEFAULT NULL COMMENT '错误描述',
  `cost_num` int(11) DEFAULT NULL COMMENT '花费元宝数量',
  `remind_num` int(11) DEFAULT NULL COMMENT '元宝剩余数量',
  `item_id` int(11) DEFAULT NULL COMMENT '获得道具id',
  `item_num` int(11) DEFAULT NULL COMMENT '获得道具数量',
  `item_name` varchar(64) DEFAULT NULL COMMENT '获得道具名字',
  `req_data` varchar(2000) DEFAULT NULL COMMENT '发送到腾讯的参数',
  `resp_date` varchar(2000) DEFAULT NULL COMMENT '腾讯返回的参数',
  `trade_mill` bigint(20) DEFAULT NULL COMMENT '交易时间',
  `trade_date` varchar(20) DEFAULT NULL COMMENT '交易日期',
  `detail` varchar(2000) DEFAULT NULL COMMENT '交易详细信息',
  `log_time` datetime DEFAULT NULL COMMENT '记录时间',
  `trade_desc` varchar(2000) DEFAULT NULL COMMENT '交易描述',
  KEY `log_money_ix1` (`log_time`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of log_consume_template_month
-- ----------------------------

-- ----------------------------
-- Table structure for `log_exp_template_month`
-- ----------------------------
DROP TABLE IF EXISTS `log_exp_template_month`;
CREATE TABLE `log_exp_template_month` (
  `player_id` bigint(20) DEFAULT NULL COMMENT '玩家ID',
  `function_name` varchar(128) DEFAULT NULL COMMENT '功能名称',
  `exp` int(11) DEFAULT NULL COMMENT '经验',
  `log_time` datetime DEFAULT NULL COMMENT '记录时间',
  `detail` varchar(2000) DEFAULT NULL COMMENT '详细信息',
  KEY `log_exp_ix1` (`log_time`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of log_exp_template_month
-- ----------------------------

-- ----------------------------
-- Table structure for `log_item_template_month`
-- ----------------------------
DROP TABLE IF EXISTS `log_item_template_month`;
CREATE TABLE `log_item_template_month` (
  `player_id` bigint(20) DEFAULT NULL COMMENT '玩家ID',
  `oper_type` int(11) DEFAULT NULL COMMENT '操作类型 1、增加 2、消耗',
  `function_name` varchar(128) DEFAULT NULL COMMENT '功能名称',
  `item_id` int(11) DEFAULT NULL COMMENT '物品ID',
  `item_count` int(11) DEFAULT NULL COMMENT '物品数量',
  `log_time` datetime DEFAULT NULL COMMENT '记录时间',
  `detail` varchar(2000) DEFAULT NULL COMMENT '详细信息',
  KEY `log_item_ix1` (`log_time`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of log_item_template_month
-- ----------------------------

-- ----------------------------
-- Table structure for `log_money_template_month`
-- ----------------------------
DROP TABLE IF EXISTS `log_money_template_month`;
CREATE TABLE `log_money_template_month` (
  `player_id` bigint(20) DEFAULT NULL COMMENT '玩家ID',
  `money_type` int(11) DEFAULT NULL COMMENT '金钱类型 1、money  2、gold',
  `oper_type` int(11) DEFAULT NULL COMMENT '操作类型 1、增加  2、消耗',
  `function_name` varchar(128) DEFAULT NULL COMMENT '功能名称',
  `money` int(11) DEFAULT NULL COMMENT '金额，消耗为负数',
  `log_time` datetime DEFAULT NULL COMMENT '记录时间',
  `detail` varchar(2000) DEFAULT NULL COMMENT '详细信息',
  KEY `log_money_ix1` (`log_time`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of log_money_template_month
-- ----------------------------

-- ----------------------------
-- Table structure for `marketingactivity`
-- ----------------------------
DROP TABLE IF EXISTS `marketingactivity`;
CREATE TABLE `marketingactivity` (
  `open_act_over_time` datetime DEFAULT NULL COMMENT '开服活动结束时间',
  `rank_award_tag` varchar(5) DEFAULT 'in' COMMENT '排行榜活动状态 in:进行中 over:已结束',
  `rankDay` int(3) DEFAULT NULL COMMENT '排行榜领取时间',
  `rankData` text COMMENT '排行榜领取数据'
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of marketingactivity
-- ----------------------------

-- ----------------------------
-- Table structure for `mobai`
-- ----------------------------
DROP TABLE IF EXISTS `mobai`;
CREATE TABLE `mobai` (
  `name` varchar(20) NOT NULL COMMENT '角色名',
  `moBai` blob NOT NULL COMMENT '膜拜、鄙视值',
  PRIMARY KEY (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of mobai
-- ----------------------------

-- ----------------------------
-- Table structure for `names`
-- ----------------------------
DROP TABLE IF EXISTS `names`;
CREATE TABLE `names` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `sex` int(11) NOT NULL,
  `name` varchar(255) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=3905 DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of names
-- ----------------------------

-- ----------------------------
-- Table structure for `offreward`
-- ----------------------------
DROP TABLE IF EXISTS `offreward`;
CREATE TABLE `offreward` (
  `id` bigint(20) NOT NULL DEFAULT '0',
  `value` blob,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of offreward
-- ----------------------------

-- ----------------------------
-- Table structure for `order_rmb`
-- ----------------------------
DROP TABLE IF EXISTS `order_rmb`;
CREATE TABLE `order_rmb` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `money` int(11) DEFAULT NULL,
  `order_id` varchar(255) DEFAULT NULL,
  `msg` text,
  `time` datetime DEFAULT NULL,
  UNIQUE KEY `id` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of order_rmb
-- ----------------------------

-- ----------------------------
-- Table structure for `outbox`
-- ----------------------------
DROP TABLE IF EXISTS `outbox`;
CREATE TABLE `outbox` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `playerId` bigint(20) NOT NULL COMMENT '发送人id',
  `inboxPlayerName` varchar(200) NOT NULL COMMENT '收件人name',
  `itemId` int(11) NOT NULL,
  `item` blob NOT NULL COMMENT '道具',
  `fromTime` bigint(20) NOT NULL COMMENT '邮件发送时间',
  `money` int(11) NOT NULL COMMENT '金钱',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of outbox
-- ----------------------------

-- ----------------------------
-- Table structure for `player`
-- ----------------------------
DROP TABLE IF EXISTS `player`;
CREATE TABLE `player` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '自动编号',
  `userId` bigint(20) NOT NULL DEFAULT '0' COMMENT '用户编号',
  `name` varchar(200) NOT NULL DEFAULT '' COMMENT '角色名',
  `sex` tinyint(1) NOT NULL DEFAULT '0' COMMENT '性别（0：男；1女）',
  `vocId` int(1) NOT NULL DEFAULT '0' COMMENT '职业编号',
  `head` varchar(20) NOT NULL DEFAULT '' COMMENT '头像编号',
  `skin` int(10) NOT NULL DEFAULT '0' COMMENT '表皮编号',
  `grade` int(3) NOT NULL DEFAULT '0' COMMENT '等级',
  `exp` bigint(20) unsigned NOT NULL DEFAULT '0' COMMENT '当前经验',
  `money` int(11) NOT NULL DEFAULT '0' COMMENT '当前金钱',
  `renown` int(11) NOT NULL DEFAULT '0' COMMENT '当前威望',
  `cashGift` int(11) NOT NULL DEFAULT '0' COMMENT '当前礼金',
  `map` text NOT NULL COMMENT '所在地图',
  `mapX` int(11) NOT NULL DEFAULT '0' COMMENT '所在坐标x',
  `mapY` int(11) NOT NULL DEFAULT '0' COMMENT '所在坐标y',
  `attackMode` int(11) NOT NULL DEFAULT '0' COMMENT '攻击模式（0：和平模式）',
  `lastLoginTime` datetime NOT NULL DEFAULT '0000-00-00 00:00:00' COMMENT '最后登录时间',
  `createTime` datetime NOT NULL DEFAULT '0000-00-00 00:00:00' COMMENT '创建时间',
  `state` int(11) NOT NULL DEFAULT '0' COMMENT '帐号状态（0：可用；1：锁定）',
  `showExtValue` blob NOT NULL COMMENT '表现扩展数据',
  `proData` blob NOT NULL COMMENT '属性数据',
  `skillData` blob NOT NULL COMMENT '技能数据',
  `buffData` blob NOT NULL COMMENT 'buff数据',
  `bagData` mediumblob NOT NULL COMMENT '背包数据',
  `equipData` blob NOT NULL COMMENT '装备数据',
  `depotData` mediumblob NOT NULL COMMENT '仓库数据',
  `taskBagData` blob NOT NULL COMMENT '任务物品背包数据',
  `taskData` blob NOT NULL COMMENT '任务数据',
  `shortCutData` blob NOT NULL COMMENT '快捷栏数据',
  `chanData` blob NOT NULL,
  `retreat` blob NOT NULL COMMENT '闭关数据',
  `pkMode` blob NOT NULL COMMENT 'PK数据',
  `automatic` blob NOT NULL COMMENT '挂机数据',
  `title` blob NOT NULL COMMENT '称号',
  `onlineTime` bigint(20) NOT NULL DEFAULT '0' COMMENT '在线总时间',
  `olAwardData` blob NOT NULL COMMENT '在线奖励',
  `vipData` blob NOT NULL COMMENT 'vip数据',
  `systemConfigData` blob NOT NULL COMMENT '系统设置',
  `eachDayAimData` blob NOT NULL COMMENT '每日目标',
  `equipRefresh` blob,
  `together` blob NOT NULL COMMENT '齐心协力',
  `huntData` blob,
  `wsRoadData` blob COMMENT '武圣目标数据',
  `maxRenown` int(11) NOT NULL DEFAULT '0' COMMENT '历史最大威望',
  `petData` mediumblob NOT NULL COMMENT '宠物数据',
  `forbidSpeakData` bigint(20) NOT NULL COMMENT '禁言时间',
  `renewContainer` blob NOT NULL COMMENT '恢复容器',
  `enhanceData` blob COMMENT '强化幸运值',
  `xiuwei` int(11) NOT NULL COMMENT '修为',
  `baoZang` mediumblob NOT NULL COMMENT '宝藏',
  `dayPlayData` mediumblob,
  `signAwardData` blob COMMENT '福利',
  `boxData` blob COMMENT '随机宝箱',
  `bless` blob NOT NULL COMMENT '好友祝福',
  `giftData` blob NOT NULL,
  `wsAimData` blob,
  `guideAllData` blob NOT NULL,
  `enterGameTag` tinyint(3) unsigned NOT NULL DEFAULT '0' COMMENT '是否进入过游戏',
  `provisional` blob NOT NULL COMMENT '临时数据',
  `oldsid` int(11) DEFAULT NULL COMMENT '合服前服务器id',
  `dramaData` blob NOT NULL COMMENT '新版侠客岛数据',
  `today` int(11) DEFAULT NULL COMMENT '一年之中第几天',
  `skillPraData` blob NOT NULL COMMENT '技能修炼',
  `dayPackageData` blob NOT NULL,
  `payStatus` int(11) DEFAULT NULL COMMENT '人物是否 拥有元宝',
  `emallPay` int(11) NOT NULL COMMENT 'emallPay',
  `marketPay` int(11) DEFAULT NULL COMMENT '市场消费',
  `pobing` blob NOT NULL COMMENT '破冰',
  `payback` blob COMMENT '消费返券',
  `loginAward` blob COMMENT '连续登陆次数',
  `dupData` blob COMMENT '副本扫荡',
  `swingData` blob COMMENT '翅膀数据',
  `depotMoney` int(11) DEFAULT NULL COMMENT '仓库存钱',
  `killNum` int(11) DEFAULT NULL COMMENT '杀怪总数',
  `bangwarAwardFlag` int(11) DEFAULT NULL,
  `chargeGold` int(11) DEFAULT NULL COMMENT '充值总额',
  `consumeGold` int(11) DEFAULT NULL COMMENT '消费总额',
  `inviter` varchar(30) DEFAULT NULL COMMENT '邀请者',
  `marketingData` blob COMMENT '运营活动',
  `rankData` mediumblob COMMENT '排行榜数据',
  `paymoney` int(11) DEFAULT NULL COMMENT '元宝',
  `serialFlag` blob COMMENT '激活码标记',
  `outlineCharge` int(11) DEFAULT '0' COMMENT '离线充值数额',
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`),
  KEY `idx_userid` (`userId`)
) ENGINE=InnoDB AUTO_INCREMENT=571734725144736641 DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of player
-- ----------------------------

-- ----------------------------
-- Table structure for `purce`
-- ----------------------------
DROP TABLE IF EXISTS `purce`;
CREATE TABLE `purce` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `playerId` bigint(20) DEFAULT NULL,
  `playerName` varchar(255) DEFAULT NULL,
  `itemId` int(11) DEFAULT NULL,
  `itemNum` int(11) DEFAULT NULL,
  `itemName` varchar(255) DEFAULT NULL,
  `itemQuality` int(11) DEFAULT NULL,
  `marketType1` int(11) DEFAULT NULL,
  `marketType2` int(11) DEFAULT NULL,
  `itemGrade` int(11) DEFAULT NULL,
  `itemByte` blob,
  `priceType` int(11) DEFAULT NULL,
  `priceNum` int(11) DEFAULT NULL,
  `createTime` bigint(11) DEFAULT NULL,
  `exitsSecond` bigint(11) DEFAULT NULL,
  `dueTime` bigint(11) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of purce
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_contribute`
-- ----------------------------
DROP TABLE IF EXISTS `rank_contribute`;
CREATE TABLE `rank_contribute` (
  `pid` bigint(20) NOT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `value` bigint(20) DEFAULT NULL COMMENT '贡献值',
  `grade` int(3) DEFAULT NULL COMMENT '等级',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_contribute
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_fightvalue`
-- ----------------------------
DROP TABLE IF EXISTS `rank_fightvalue`;
CREATE TABLE `rank_fightvalue` (
  `pid` bigint(20) NOT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `grade` int(3) DEFAULT NULL COMMENT '等级',
  `value` bigint(20) DEFAULT NULL COMMENT '战力值',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_fightvalue
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_gold`
-- ----------------------------
DROP TABLE IF EXISTS `rank_gold`;
CREATE TABLE `rank_gold` (
  `pid` bigint(20) NOT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `grade` int(3) DEFAULT NULL COMMENT '等级',
  `value` int(11) DEFAULT NULL COMMENT '消费额度',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_gold
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_grade`
-- ----------------------------
DROP TABLE IF EXISTS `rank_grade`;
CREATE TABLE `rank_grade` (
  `pid` bigint(20) NOT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `grade` int(3) DEFAULT NULL COMMENT '等级',
  `value` bigint(20) DEFAULT NULL COMMENT '当前经验',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_grade
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_killboss`
-- ----------------------------
DROP TABLE IF EXISTS `rank_killboss`;
CREATE TABLE `rank_killboss` (
  `pid` bigint(20) NOT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `grade` int(3) DEFAULT NULL COMMENT '等级',
  `value` bigint(20) DEFAULT NULL COMMENT '击杀Boss',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_killboss
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_mount`
-- ----------------------------
DROP TABLE IF EXISTS `rank_mount`;
CREATE TABLE `rank_mount` (
  `pid` bigint(20) DEFAULT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `onlyid` bigint(20) NOT NULL COMMENT '唯一编号',
  `value` bigint(20) DEFAULT NULL COMMENT '坐骑战力',
  `ranktime` datetime DEFAULT NULL COMMENT '记录时间',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`onlyid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_mount
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_pet`
-- ----------------------------
DROP TABLE IF EXISTS `rank_pet`;
CREATE TABLE `rank_pet` (
  `pid` bigint(20) NOT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `petid` int(11) NOT NULL COMMENT '侠客编号',
  `value` bigint(20) DEFAULT NULL COMMENT '侠客战力',
  `ranktime` datetime DEFAULT NULL COMMENT '记录时间',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`pid`,`petid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_pet
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_pvpkill`
-- ----------------------------
DROP TABLE IF EXISTS `rank_pvpkill`;
CREATE TABLE `rank_pvpkill` (
  `pid` bigint(20) NOT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `grade` int(3) DEFAULT NULL COMMENT '等级',
  `value` bigint(20) DEFAULT NULL COMMENT '杀敌数',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_pvpkill
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_relive`
-- ----------------------------
DROP TABLE IF EXISTS `rank_relive`;
CREATE TABLE `rank_relive` (
  `pid` bigint(20) NOT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `grade` int(3) DEFAULT NULL COMMENT '等级',
  `value` bigint(20) DEFAULT NULL COMMENT '复活次数',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_relive
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_up`
-- ----------------------------
DROP TABLE IF EXISTS `rank_up`;
CREATE TABLE `rank_up` (
  `pid` bigint(20) NOT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `value` bigint(20) DEFAULT NULL COMMENT '爬塔层数',
  `ranktime` int(11) DEFAULT NULL COMMENT '消耗时间',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_up
-- ----------------------------

-- ----------------------------
-- Table structure for `rank_winespirit`
-- ----------------------------
DROP TABLE IF EXISTS `rank_winespirit`;
CREATE TABLE `rank_winespirit` (
  `pid` bigint(20) NOT NULL COMMENT '角色编号',
  `name` varchar(200) DEFAULT NULL COMMENT '角色名',
  `grade` int(3) DEFAULT NULL COMMENT '等级',
  `value` bigint(20) DEFAULT NULL COMMENT '酒魂值',
  `vipdata` blob COMMENT 'vip数据',
  PRIMARY KEY (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rank_winespirit
-- ----------------------------

-- ----------------------------
-- Table structure for `reward`
-- ----------------------------
DROP TABLE IF EXISTS `reward`;
CREATE TABLE `reward` (
  `pid` bigint(20) NOT NULL COMMENT '人物id',
  `renown` int(11) NOT NULL COMMENT '威望',
  `money` int(11) NOT NULL COMMENT '金钱',
  `time` bigint(20) NOT NULL COMMENT '时间',
  `exp` int(11) NOT NULL COMMENT '离线奖励经验',
  PRIMARY KEY (`pid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of reward
-- ----------------------------

-- ----------------------------
-- Table structure for `rmb`
-- ----------------------------
DROP TABLE IF EXISTS `rmb`;
CREATE TABLE `rmb` (
  `name` varchar(255) DEFAULT NULL COMMENT '玩家名',
  `openid` varchar(255) DEFAULT NULL COMMENT '登陆名',
  `money` int(11) DEFAULT '0' COMMENT '金额',
  `oldmoney` int(11) DEFAULT '0' COMMENT '改变前',
  `newmoney` int(11) DEFAULT '0' COMMENT '改变后',
  `realcost` int(11) DEFAULT '0' COMMENT '实际消耗的人民币',
  `ptype` varchar(10) DEFAULT NULL COMMENT '操作类型',
  `mtype` varchar(10) DEFAULT NULL COMMENT '货币类型',
  `itemname` varchar(255) DEFAULT NULL COMMENT '道具名',
  `price` int(11) DEFAULT NULL COMMENT '道具价格',
  `num` int(11) DEFAULT NULL COMMENT '道具数量',
  `detail` varchar(255) DEFAULT NULL COMMENT '详细',
  `time` datetime DEFAULT NULL COMMENT '时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of rmb
-- ----------------------------

-- ----------------------------
-- Table structure for `server_config`
-- ----------------------------
DROP TABLE IF EXISTS `server_config`;
CREATE TABLE `server_config` (
  `id` int(11) NOT NULL DEFAULT '0' COMMENT 'server id',
  `loginurl` varchar(255) DEFAULT NULL,
  `cdnurl` varchar(255) DEFAULT NULL COMMENT 'cdn url',
  `chargeurl` varchar(255) DEFAULT NULL COMMENT 'charge url',
  `serverip` varchar(255) DEFAULT NULL,
  `serverport` int(11) DEFAULT NULL,
  `gmurl` varchar(255) DEFAULT NULL COMMENT '公用gm连接url',
  `zoneid` varchar(20) DEFAULT NULL COMMENT '区服id',
  `key` varchar(255) DEFAULT NULL COMMENT '登录密钥',
  `depotid` varchar(20) DEFAULT NULL COMMENT '平台id',
  `sendURL` varchar(255) DEFAULT NULL COMMENT '数据中心地址',
  `logPath` varchar(255) DEFAULT NULL COMMENT '日志服文件生成路径',
  `appid` varchar(255) DEFAULT NULL COMMENT '腾讯appid',
  `appkey` varchar(255) DEFAULT NULL COMMENT '腾讯appkey',
  `qqdebug` tinyint(1) DEFAULT NULL COMMENT '腾讯debug模式',
  `qqsell` tinyint(1) DEFAULT NULL COMMENT '腾讯商城购买开关',
  `appservername` varchar(255) DEFAULT NULL COMMENT '腾讯调试服务器地址',
  `gmopen` tinyint(1) DEFAULT NULL COMMENT '服务器gm开关',
  `opentime` datetime DEFAULT NULL COMMENT '开服时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of server_config
-- ----------------------------
INSERT INTO `server_config` VALUES ('1', 'http://127.0.0.1/', 'http://127.0.0.1/', 'http://127.0.0.1/', '127.0.0.1', '7777', 'http://127.0.0.1/', '999', '!GameWave111', '999', 'http://127.0.0.1/gamelog/', '/data/gamelogs/', 'a001', 'a001', '1', '1', '127.0.0.1', '1', '2014-02-07 12:44:24');
INSERT INTO `server_config` VALUES ('2', 'http://127.0.0.1/', 'http://127.0.0.1/', 'http://127.0.0.1/', '127.0.0.1', '7777', 'http://127.0.0.1/', '888', 'http://127.0.0.1/', '888', 'http://127.0.0.1/gamelog/', '/data2/gamelogs/', 'a002', 'a002', '1', '1', '127.0.0.1', '1', '2014-02-25 04:19:51');

-- ----------------------------
-- Table structure for `territory`
-- ----------------------------
DROP TABLE IF EXISTS `territory`;
CREATE TABLE `territory` (
  `scene` varchar(20) DEFAULT NULL,
  `grade` int(11) DEFAULT NULL,
  `exp` int(11) DEFAULT NULL,
  `capture` varchar(50) DEFAULT NULL,
  `plusmember` int(11) DEFAULT NULL
) ENGINE=MyISAM DEFAULT CHARSET=latin1;

-- ----------------------------
-- Records of territory
-- ----------------------------

-- ----------------------------
-- Table structure for `trade`
-- ----------------------------
DROP TABLE IF EXISTS `trade`;
CREATE TABLE `trade` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `playerId` bigint(20) DEFAULT NULL,
  `playerName` varchar(255) DEFAULT NULL,
  `itemId` int(11) DEFAULT NULL,
  `itemNum` int(11) DEFAULT NULL,
  `itemName` varchar(255) DEFAULT NULL,
  `itemQuality` varchar(255) DEFAULT NULL,
  `marketType1` int(11) DEFAULT NULL,
  `marketType2` int(11) DEFAULT NULL,
  `itemGrade` int(11) DEFAULT NULL,
  `itemByte` blob,
  `priceType` int(11) DEFAULT NULL,
  `priceNum` int(11) DEFAULT NULL,
  `createTime` bigint(11) DEFAULT NULL,
  `sellerOpenId` varchar(255) DEFAULT NULL COMMENT '卖家QQ平台ID',
  `exitsSecond` bigint(11) DEFAULT NULL,
  `dueTime` bigint(11) DEFAULT NULL,
  `qqLevel` int(11) DEFAULT NULL COMMENT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of trade
-- ----------------------------

-- ----------------------------
-- Table structure for `user`
-- ----------------------------
DROP TABLE IF EXISTS `user`;
CREATE TABLE `user` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `loginName` varchar(50) COLLATE utf8_bin NOT NULL COMMENT '用户名',
  `isOnline` tinyint(4) DEFAULT NULL COMMENT '最后一次sessionId',
  `loginTime` datetime DEFAULT NULL COMMENT '登陆时间',
  `logoutTime` datetime DEFAULT NULL COMMENT '登出时间',
  `createdTime` datetime DEFAULT NULL COMMENT '创建时间',
  `type` tinyint(4) DEFAULT NULL COMMENT '角色类型',
  `lastLoginIp` int(20) DEFAULT NULL COMMENT '上次登陆ip',
  `isCharged` tinyint(4) DEFAULT NULL COMMENT '是否充值',
  `money` int(11) NOT NULL DEFAULT '0' COMMENT '充值币',
  `sessionOutTime` datetime DEFAULT NULL COMMENT '会话过期时间',
  `countTime` int(11) NOT NULL DEFAULT '0' COMMENT '已在线总时间',
  `userFrom` varchar(20) COLLATE utf8_bin DEFAULT '',
  `allow` tinyint(3) unsigned NOT NULL DEFAULT '0' COMMENT '是否成年，0 已成年，1未成年',
  `lockMill` datetime DEFAULT NULL COMMENT '封停截止时间',
  `trust` int(1) NOT NULL COMMENT '是否托管',
  `oldsid` int(11) NOT NULL COMMENT '选择登陆的区id',
  `via` varchar(255) COLLATE utf8_bin DEFAULT NULL COMMENT '用户来源',
  PRIMARY KEY (`id`),
  UNIQUE KEY `loginName` (`loginName`)
) ENGINE=InnoDB AUTO_INCREMENT=571734688738177921 DEFAULT CHARSET=utf8 COLLATE=utf8_bin CHECKSUM=1 DELAY_KEY_WRITE=1 ROW_FORMAT=DYNAMIC;

-- ----------------------------
-- Records of user
-- ----------------------------
