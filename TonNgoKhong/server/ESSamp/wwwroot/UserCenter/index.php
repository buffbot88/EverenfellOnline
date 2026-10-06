

<!DOCTYPE html>

<html xmlns="http://www.w3.org/1999/xhtml">
<head><meta http-equiv="X-UA-Compatible" content="IE=EmulateIE7" />
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<?php 
  include_once "../configuration/config.inc.php";
   if(!$_SESSION['accountName']) exit("<script>location.href='Login.php';</script>");
?>
<title>	
        <?php echo $WebTitle; ?>-Tuan565
</title>
<link href="/ClientRes/Styles/BasicStyle.css?_v=634979371913162195" type="text/css" rel="stylesheet" />
<link href="/ClientRes/Styles/jquery-ui.min.css?_v=634979244165085356" type="text/css" rel="stylesheet" />
<link href="/ClientRes/Styles/jmodal.css?_v=634979244164935253" type="text/css" rel="stylesheet" />
<link href="/ClientRes/Styles/loading.css?_v=634979244165185438" type="text/css" rel="stylesheet" />
<script src="//ajax.googleapis.com/ajax/libs/jquery/1.8.3/jquery.min.js" type="text/javascript" charset="UTF-8"></script>
 <!--如果google CDN不正常，就从本地获取JQ库。--> 
<script>!window.jQuery && document.write('<script src="/ClientRes/Scripts/jquery.min.js"><\/script>');</script>
<script src="/ClientRes/Scripts/jquery-ui.min.js?_v=634979244162663753" type="text/javascript" charset="UTF-8"></script>
<script src="/ClientRes/Scripts/jmodal.js?_v=634979244161903250" type="text/javascript" charset="UTF-8"></script>
<script src="/ClientRes/Scripts/loading.js?_v=634979244164224791" type="text/javascript" charset="UTF-8"></script>
<script src="/ClientRes/Scripts/Common.js?_v=634979706622125062" type="text/javascript" charset="UTF-8"></script>
<script src="/ClientRes/Scripts/Extends.js?_v=634979244161412905" type="text/javascript" charset="UTF-8"></script>
<script src="/ClientRes/Scripts/AjaxRequest.js?_v=634979244161282816" type="text/javascript" charset="UTF-8"></script></head>

<?php 
require '../TempLate/PublicTop.html';//引用模板 
?> 
    <div class="center clearfix mt10">
        <div class="c_main">
<?php 
require '../TempLate/LeftNav.html';//引用模板
	$username=$_SESSION['accountName'];
	$sql="SELECT * FROM dntg.user_role WHERE ='".$username."'";
	$result=mysql_query($sql);
	$dhyb=$total*$tgyuanbao;
	$timestamp = time();
	
?> 
<div class="center_right ml10">
    <!--无邮箱提示开始 检测到无邮箱才显示-->
    
    <!--无邮箱提示结束-->


    <div class="basicInfo">
        <div class="basicInfo_content">
            <p>
                Tài khoản:<b class="orange"><?php echo $username;?></b><b
                        
            </p>
           
            <p>
                Thông tin xúc tiến: Hiện tại <b class="orange"><?php echo $total;?></b>sắp đạt <b class="orange"><?php echo $lv;?></b> lên cấp<b class="segmentation"></b>Chuyển <b class="orange"><?php echo $dhyb;?></b> KNB<b class="segmentation"></b>Thưởng <b class="orange"><?php echo $tgyuanbao;?> KNB</b>
                
            </p>
            <p>
				<a href="/Gamelogin.php"  class="bt_but c_1_g mr10 tips" target=_blank><u></u>Vào game</a>
				<a  onclick="SignOut();"   class="bt_but c_1_g mr10 tips"><u></u>Đăng xuất</a></a>
            </p>

        </div>

        <div class="basicInfo_currency">
            <ul class="clearfix">
                <li><span class="orange">Thông báo:</span> <span>
                    <?php echo $row3['dj'];?></span> </li>
<li><a>Mẹo: Vào Tuan565.blogspot.com
</a></li>
					            </ul>
        </div>
    </div>
    <div class="basicInfor-content-shadow">
    </div>
    <div class="mybox">
        <script type="text/javascript">
            $(function () {
                $.ajaxSetup({ cache: false });
                $("#tabs").tabs();
            })
        </script>
  <div class="mytit">
            Thông tin[<b class="orange">Tuan565.blogspot.com</b>]
        </div>
        <div class="myinfo_con clearfix">
          <script type="text/javascript">
                $(function () {
                    <?php 
						if(!$row || !is_array($row)){
							echo '$'.'("#tabs").html("<strong>您还没有创建角色，创建角色后可在此处领取推广元宝</strong>")';
						}
					?>
                })
            </script>
<div id="tabs" class="ui_tabs">
                <ul>
                    <li><a href="#tabs-1"><?php echo $row['name'];?></a></li>
                </ul>
                <div id="tabs-1">	<p>
            角色名字：<b class="orange"><?php echo $row['name'];?></b>&nbsp;|&nbsp;Cấp độ:<b class="orange"><?php echo $row['grade'];?></b>&nbsp;|&nbsp;角色经验：<b class="orange"><?php echo $row['exp'];?></b>&nbsp;|&nbsp;角色礼金：<b class="orange"><?php echo $row['cashGift'];?></b>&nbsp;|&nbsp;</b>当前金钱：<b class="orange"><?php echo $row['money'];?></b>&nbsp;|&nbsp;当前元宝：<b class="orange"><?php echo $row['paymoney'];?></b>
	</p>
元宝领取：<a  href="/coon/de.php"   class="bt_but c_1_g mr10 tips"><u></u>领取充值元宝</a>
推广领取：<a  onclick="SpreadTran()"   class="bt_but c_1_g mr10 tips"><u></u>领取推广元宝</a>
   
        </div>
    </div>
</div></div>
<div class="basicInfor-content-shadow">
    </div>


</div>
</div></div>
<?php 
require '../TempLate/PublicButtom.html';//引用模板 
?> 
</html>
