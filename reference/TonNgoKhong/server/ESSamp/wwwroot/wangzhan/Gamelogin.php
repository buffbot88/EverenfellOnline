<?php 
  include_once "configuration/config.inc.php";
   if(!$_SESSION['accountName']) exit("<script> alert('请登陆后使用！');location.href='UserCenter/Login.php';</script>");
?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<!-- saved from url=(0014)about:internet -->
<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en"> 
    <!-- 
    Smart developers always View Source. 
    
    This application was built using Adobe Flex, an open source framework
    for building rich Internet applications that get delivered via the
    Flash Player or to desktops via Adobe AIR. 
    
    Learn more about Flex at http://flex.org 
    // -->
    <head>
        <title></title>
        <meta name="google" value="notranslate" />         
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
        <!-- Include CSS to eliminate any default margins/padding and set the height of the html element and 
             the body element to 100%, because Firefox, or any Gecko based browser, interprets percentage as 
             the percentage of the height of its parent container, which has to be set explicitly.  Fix for
             Firefox 3.6 focus border issues.  Initially, don't display flashContent div so it won't show 
             if JavaScript disabled.
        -->
        <style type="text/css" media="screen"> 
            html, body  { height:100%; }
            body { margin:0; padding:0; overflow:auto; text-align:center; 
                   background-color: #0; }   
            object:focus { outline:none; }
            #flashContent { display:none; }
        </style>
        
        <!-- Enable Browser History by replacing useBrowserHistory tokens with two hyphens -->
        <!-- BEGIN Browser History required section -->
        <link rel="stylesheet" type="text/css" href="history.css" />
        <script type="text/javascript" src="history.js"></script>
        <script type="text/javascript" src="swfobject.js"></script>
		<script>
			var search = window.location.search;

	
			function getValue(val)
			{
				var regExp = new RegExp(val+"=([^&?]*)", "ig");
				return (search.match(regExp)?search.match(regExp)[0].substring(val.length+1):null);
			}

			function GetQueryString(name) 
			{ 
			
 				if(name=="uid"){
                                                return "api_key=S1&cm_flag=n&server_id=999&user_id=<?php echo $_SESSION['accountName'];?>&sign=1A9110F972D7DE7AC43D6A7540D521DC";
/**						
return 'guard_wallow='+getValue("guard_wallow")+'&user_id='+getValue("user_id")+'&user_from=' +getValue("user_from")+ '&time=' +getValue("time")+ '&sign=' +getValue("sign");
*/
				}else{
					return getValue(name);
				}
				
				/**
				 var reg = new RegExp("(^|&)"+ name +"=([^&]*)(&|$)"); 
				 var r = window.location.search.substr(1).match(reg); 
				 if(r!=null){
						return unescape(r[2]);
					}
						
				  return null; 

				*/
			}
			function myrefresh()
			{
				window.location.reload();
			}
			function savePage()

			{
   
			if (document.all)
   
			{
window.external.addFavorite('http://wx.400youxi.com','ws');
}
			else if (window.sidebar)

			{
window.sidebar.addPanel('ws', 'http://wx.400youxi.com', "");}
}

		window.onbeforeunload = function (e) {
			  var str=swfobject.getObjectById("main").quitGame();
				if(str==""||str==null){
                                  
				}
                                else
                                {
                                 return str;
                                }
		};
                
                function openLog()
                {
                     swfobject.getObjectById("main").log();
		}

                function qqBuy()
                {
                     //alert("QQ buy panel will be pop after runing qq platform");
                 }
                function pay()
                {
                     //alert("pay");
                 }
                 function fcm()
                {
                     //alert("fcm");
                      document.getElementById("main").fcm(1);
                 }
                  function invite(msg,img)
                {
                    // alert("invite");
		      window.console && console.info(msg);
                      window.console && console.info(img);
			var ids = ['08B8273CACFBE0D9F57CAB4E7D8BDBF0','9CE729C9927532BABBB57F6AB000925B'];
                      document.getElementById("main").invite(ids);
                 }
		function share(desc,summary,title,pics)
                {
                       // alert("share "+ desc +"  "+summary+"  "+title+"  "+pics);
                       document.getElementById("main").share();

                }

		function openVipGift(tokenid){
			window.console && console.info(tokenid);
			document.getElementById("main").log("openvipgift "+tokenid);
		}
		function addDesktopUrl() {
	var pf=getValue("pf");
	var url="http://10.1.101.8/cx/assets/favorite/pengyou/?????VIP?????.url";
	if (pf == 'qzone') {
		url= "http://app100659110.imgcache.qzoneapp.com/app100659110/main/favorite/qzone/?????VIP?????.url";
	} else if (pf == 'pengyou') {
		url= "http://app100659110.imgcache.qzoneapp.com/app100659110/main/favorite/pengyou/?????VIP?????.url";
	}
	var url="http://wx.400youxi.com/";
	try {
		if (document.all) {
			var a = document.createElement("A");
			a.target = "_blank";
			a.href = url;
			document.body.appendChild(a);
			a.click();
			setTimeout(function() { a.parentNode.removeChild(a); }, 50);
		}
		else window.open(url, "_blank");
	} catch (e) {
		alert(e);
	}
	
}	

	 </script>

        <!-- END Browser History required section -->
        <script type="text/javascript">
            // For version detection, set to min. required Flash Player version, or 0 (or 0.0.0), for no version detection. 
            var swfVersionStr = "10.3.0";
            // To use express install, set to playerProductInstall.swf, otherwise the empty string. 
            var xiSwfUrlStr = "playerProductInstall.swf";
            var flashvars = {};
			var weburl="http://www.400youxi.com:888";
			flashvars.res = weburl;
			flashvars.version = Math.random()*100;
			flashvars.server="219.129.237.71";
			flashvars.port="7777";
                        flashvars.login="http://www.400youxi.com:888/";
                        flashvars.vssign=Math.random()*100;
                        flashvars.charge="http://www.400youxi.com:888";
                         flashvars.debug="off";
                   //flashvars.log="http://wx.400youxi.com/gamelog/";      
	    var params = {};
            params.quality = "high";
            params.bgcolor = "#0";
            params.allowscriptaccess = "always";
            params.allowfullscreen = "true";
            params.wmode="win";
            var attributes = {};
            attributes.id = "main";
            attributes.name = "Main";
            attributes.align = "middle";
            swfobject.embedSWF(
                weburl+"/MainLoader.swf", "flashContent", 
                "100%", "100%", 
                swfVersionStr, xiSwfUrlStr, 
                flashvars, params, attributes);
            // JavaScript enabled so display the flashContent div in case it is not replaced with a swf object.
            swfobject.createCSS("#flashContent", "display:block;text-align:left;");
        </script>
    </head>
    <body>
        <!-- SWFObject's dynamic embed method replaces this alternative HTML content with Flash content when enough 
             JavaScript and Flash plug-in support is available. The div is initially hidden so that it doesn't show
             when JavaScript is disabled.
        -->
        <div id="flashContent">
            <p>
                To view this page ensure that Adobe Flash Player version 
                10.0.3 or greater is installed. 
            </p>
            <script type="text/javascript"> 
                var pageHost = ((document.location.protocol == "https:") ? "https://" : "http://"); 
                document.write("<a href='http://www.adobe.com/go/getflashplayer'><img src='./get_flash_player.gif' alt='Get Adobe Flash player' /></a>" ); 
            </script> 
        </div>
        
        <noscript>
            <object classid="clsid:D27CDB6E-AE6D-11cf-96B8-444553540000" width="1000" height="600" id="js">
                <param name="movie" value="MainLoader.swf" />
                <param name="quality" value="high" />
                <param name="bgcolor" value="#ffffff" />
                <param name="allowScriptAccess" value="sameDomain" />
                <param name="allowFullScreen" value="true" />
                <!--[if !IE]>-->
                <object type="application/x-shockwave-flash" data="MainLoader.swf" width="1000" height="600">
                    <param name="quality" value="high" />
                    <param name="bgcolor" value="#ffffff" />
                    <param name="allowScriptAccess" value="sameDomain" />
                    <param name="allowFullScreen" value="true" />
                <!--<![endif]-->
                <!--[if gte IE 6]>-->
                    <p> 
                        Either scripts and active content are not permitted to run or Adobe Flash Player version
                        10.2.0 or greater is not installed.
                    </p>
                <!--<![endif]-->
                    <a href="http://www.adobe.com/go/getflashplayer">
                        <img src="http://www.adobe.com/images/shared/download_buttons/get_flash_player.gif" alt="Get Adobe Flash Player" />
                    </a>
                <!--[if !IE]>-->
                </object>
                <!--<![endif]-->
            </object>
        </noscript>     
   </body>
</html>
