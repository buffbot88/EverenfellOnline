<?php
// JSON game-session endpoint for the new Vite/Phaser web client (client/).
//
// Issues exactly the same login token the Flash client received as flashvars
// in Gamelogin.php: uid / t / sign where sign = md5(uid . 'xianlingkey' . t).
// The game socket (127.0.0.1:8008) authenticates with these values.
//
// NOTE: seid/sport/ip/pid below are kept byte-identical to Gamelogin.php.
// They intentionally differ from config/server-info.properties (server_id=fu0);
// do not "fix" them without testing against the running game server.
header('Content-Type: application/json; charset=utf-8');
include_once dirname(__FILE__) . '/configuration/config.inc.php'; // starts session, opens MySQL

if (empty($_SESSION['accountName'])) {
    header('HTTP/1.0 401 Unauthorized');
    echo json_encode(array('ok' => false, 'error' => 'not-logged-in'));
    exit;
}

$userid = $_SESSION['accountName'];
$time = time();
echo json_encode(array(
    'ok'    => true,
    'uid'   => $userid,
    't'     => $time,
    'sign'  => md5($userid . 'xianlingkey' . $time),
    'seid'  => 'fu1304',
    'sport' => 8008,
    'ip'    => '127.0.0.1',
    'pid'   => 'gmthai',
));
