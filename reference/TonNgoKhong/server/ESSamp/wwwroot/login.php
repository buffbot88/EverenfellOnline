<?php 
	$userid = $_GET['username'];
	$time = time();
	$sid = md5($userid.'xianlingkey'.$time);
?>




<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<meta http-equiv="Cache-Control" content="no-cache" />
<link rel="shortcut icon" href="" type="image/x-icon" />
<title>8090-tiangong</title>
<style type="text/css">
html,body{ 
	margin:0; 
	height:100%; 
	padding:0;
	overflow:hidden;
	background-color: #000;
}


#container {
	position:relative;
	margin:auto;
	color:#3f3;
	text-align:center;
	font-size:30px;
	height:100%;
}
#MPlayer{
	width:10px;
	height:1px;
	margin:0 auto;
	margin-left:150px;
	position:absolute;
	z-index: 10;
	background-color:#000;
}
</style>
<script type="text/javascript" src="http://111.73.45.9/res/js/swfobject.js"></script>


<script type="text/javascript">
	function $g(id)
	{
		return document.getElementById(id);
	}
	
	var unloadFlag = true;
	var unloadStr = "是否要退出大闹天宫";
	function setUnloadString(str)
	{
		unloadStr = str;
	}
	
	function setUnloadFlag()
	{
		unloadFlag = false;
	}
	
  	window.onbeforeunload = function(event){
		if(unloadFlag)
		{
			if(addfavorite('baidu-大闹天宫','http://danao.baidu.com')==false){
				return unloadStr;
			}
		}
	}
	function addfavorite(title,url){
		if (document.all){
			window.external.addFavorite(url,title);
		}else if (window.sidebar){
			window.sidebar.addPanel(title, url, "");
		}else{
			return false;
		}
		return true;
	}
	
    var swfVersionStr = "10.0.0";
    var xiSwfUrlStr = "";
    var params = {
				menu: "false",
				scale: "noScale",
				allowFullscreen: "true",
				allowScriptAccess: "always",
				wmode:"direct"
			};
    var attributes = {
				id:"Main"
			};
			
			
    var flashvars =
	{
		lcid:(new Date()).valueOf().toString(16) + (Math.random() * 1000 >>0).toString(16),
		pay:escape('http://www.google.com.hk'),
		cm:escape('http://www.google.com.hk'),
		uid:'<?php echo $userid;?>',
		pid:'gmthai',
		t:'<? echo $time;?>',
		seid:'fu1304',
		sport:'8008',
		ip:'113.107.250.85',
		who:'',
		sign:'<? echo $sid;?>',
		cminfo:'null',
		bbsurl:escape('http://www.google.com.hk'),
		homeurl:escape('http://www.google.com.hk'),
		infourl:escape('http://www.google.com.hk'),
		shownav:escape('0'),
		bugurl:escape('http://www.gmthai.com/in_game/service?game_id=10&user_id=shidian001'),
		suggesturl:escape('http://www.gmthai.com/in_game/service?game_id=10 &user_id=shidian001'),
		saveUrl:escape('http://www.google.com.hk'),
		pl:'null',
		client:'null',
		microClientURL:escape('http://www.google.com.hk'),
		gmpanel:'0',
		server: 'null',
		gameid: 'null'
		
	};
			
	var domain = "http://111.73.45.9/res/";
	if(domain)
	{
		var base = document.createElement("base");
		var head = document.getElementsByTagName("head")[0];
		base.href = domain;
		head.appendChild(base);
	}
	
	var swf = domain + "Main.swf?" + (new Date()).valueOf().toString(16);
	function load()
	{
		swfobject.embedSWF(
	    swf, "Main",
	    "100%", "100%",
	    swfVersionStr, xiSwfUrlStr,
	    flashvars, params, attributes);
			
		swfobject.embedSWF( domain + "MPlayer.swf","MPlayer","10","2", swfVersionStr,xiSwfUrlStr,flashvars);
	}
    
</script>

</head>
<body onload="load()">
	<div id="container">
    	<div id="MPlayer"></div>
		<!-- 当得到足够的 JavaScript 和 Flash 插件支持时，SWFObject 的动态嵌入方法将此可替代 HTML 内容替换为 Flash 内容。 -->
		<div id="Main"> <a href="http://www.adobe.com/go/getflash"> 点此下载最新版Flash Player </a>
          <p>此页要求 Flash Player 版本 10.0.0 或更高版本。</p>
        </div>
	</div>
</body>
</html>
t  