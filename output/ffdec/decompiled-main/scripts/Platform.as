package
{
   import com.youbt.asm.*;
   import com.youbt.manager.RFSystemManager;
   import flash.display.Loader;
   import flash.display.LoaderInfo;
   import flash.display.Sprite;
   import flash.display.StageAlign;
   import flash.display.StageQuality;
   import flash.display.StageScaleMode;
   import flash.events.Event;
   import flash.events.IEventDispatcher;
   import flash.events.IOErrorEvent;
   import flash.events.ProgressEvent;
   import flash.events.SecurityErrorEvent;
   import flash.external.ExternalInterface;
   import flash.filters.GlowFilter;
   import flash.net.URLRequest;
   import flash.net.URLStream;
   import flash.system.ApplicationDomain;
   import flash.system.Capabilities;
   import flash.system.LoaderContext;
   import flash.text.TextField;
   import flash.text.TextFormat;
   import flash.text.TextFormatAlign;
   import flash.ui.ContextMenu;
   import flash.ui.ContextMenuItem;
   import flash.utils.ByteArray;
   import flash.utils.setTimeout;
   import show.Show;
   
   [SWF(width="1000", height="600", backgroundColor="#000000", frameRate="33")]
   public final class Platform extends Sprite
   {
      
      Platform.prototype.dll = function(param1:String):*
      {
         return new this._loc_1();
      };
      
      private var param:String = "";
      
      private var txt:TextField;
      
      private var _loc_1:Class = Platform__loc_1;
      
      public function Platform()
      {
         var _loc3_:String = null;
         super();
         if(!stage)
         {
            return;
         }
         this.loaderInfo.addEventListener(Event.COMPLETE,this.init);
         RFSystemManager.getInstance().vaildateDisplayList(this);
         RFSystemManager.getInstance().setStage(stage);
         stage.scaleMode = StageScaleMode.NO_SCALE;
         stage.quality = StageQuality.MEDIUM;
         stage.align = StageAlign.TOP_LEFT;
         var _loc1_:String = loaderInfo.loaderURL;
         var _loc2_:int = _loc1_.lastIndexOf("?");
         if(_loc2_ > -1)
         {
            this.param = _loc1_.substr(_loc2_);
         }
         try
         {
            this.contextMenu = this.contextMenu || new ContextMenu();
            this.contextMenu.hideBuiltInItems();
            this.contextMenu.customItems.push(new ContextMenuItem(Version.ver,false,true));
            _loc3_ = Capabilities.version.toString();
            if(Capabilities.isDebugger)
            {
               _loc3_ += "D";
            }
            this.contextMenu.customItems.push(new ContextMenuItem(_loc3_,false,true));
         }
         catch(e:Error)
         {
         }
      }
      
      private function init(param1:Event) : void
      {
         this.loaderInfo.removeEventListener(Event.COMPLETE,this.init);
         try
         {
            if(ExternalInterface.available)
            {
               ExternalInterface.call("eval","if(completeCallBack && typeof(completeCallBack) == \'function\'){completeCallBack()}");
            }
         }
         catch(e:Error)
         {
         }
         this.txt = this.createTxt();
         addChild(new Show(this.txt));
         setTimeout(this.t,300);
      }
      
      private function createTxt() : TextField
      {
         var _loc1_:TextField = new TextField();
         _loc1_.textColor = 16777215;
         _loc1_.filters = [new GlowFilter(16777215,0.3,2,2,20)];
         var _loc2_:TextFormat = new TextFormat();
         _loc2_.align = TextFormatAlign.CENTER;
         _loc1_.defaultTextFormat = _loc2_;
         return _loc1_;
      }
      
      private function t() : void
      {
         var _loc1_:URLStream = new URLStream();
         _loc1_.addEventListener(Event.COMPLETE,this.uc);
         _loc1_.addEventListener(IOErrorEvent.IO_ERROR,this.err);
         _loc1_.addEventListener(SecurityErrorEvent.SECURITY_ERROR,this.err);
         _loc1_.load(new URLRequest("PlatformLoader.swf?v=" + Version.ver));
      }
      
      private function uc(param1:Event) : void
      {
         var _loc4_:Loader = null;
         var _loc2_:URLStream = param1.currentTarget as URLStream;
         _loc2_.removeEventListener(Event.COMPLETE,this.uc);
         _loc2_.removeEventListener(IOErrorEvent.IO_ERROR,this.err);
         var _loc3_:ByteArray = new ByteArray();
         _loc2_.readBytes(_loc3_);
         if(_loc3_.length == Version.HASH)
         {
            _loc4_ = new Loader();
            _loc4_.contentLoaderInfo.addEventListener(Event.COMPLETE,this.lc);
            _loc4_.contentLoaderInfo.addEventListener(IOErrorEvent.IO_ERROR,this.err);
            _loc4_.loadBytes(_loc3_,new LoaderContext(false,ApplicationDomain.currentDomain));
         }
         else
         {
            this.eee(null);
         }
      }
      
      private function err(param1:IOErrorEvent) : void
      {
         var _loc2_:IEventDispatcher = param1.currentTarget as IEventDispatcher;
         _loc2_.removeEventListener(Event.COMPLETE,this.uc);
         _loc2_.removeEventListener(IOErrorEvent.IO_ERROR,this.err);
         _loc2_.removeEventListener(Event.COMPLETE,this.lc);
         this.eee(null);
      }
      
      private function lc(param1:Event) : void
      {
         var _loc2_:LoaderInfo = param1.currentTarget as LoaderInfo;
         addChild(_loc2_.content);
         var _loc3_:Loader = new Loader();
         _loc3_.contentLoaderInfo.addEventListener(Event.COMPLETE,this.onComplete);
         var _loc4_:ByteArray = this["dll"]("http://www.g.cn/dll.png");
         var _loc5_:int = 0;
         _loc5_ = 282449088;
         _loc5_ += 1;
         _loc5_ = _loc5_ << 1;
         _loc5_ <<= 1;
         _loc3_.loadBytes(_loc4_,new LoaderContext(false,ApplicationDomain.currentDomain));
         addChildAt(this.txt,0);
      }
      
      private function onComplete(param1:Event) : void
      {
         var _loc2_:Object = param1.target.content;
         var _loc3_:ByteArray = new ByteArray();
         _loc3_.writeByte(0);
         _loc3_.writeByte(1);
         _loc3_.writeByte(114);
         _loc3_.position = 0;
         var _loc4_:String = "assets/tg.swf?v=";
         _loc2_[_loc3_.readUTF()]([_loc4_ + Version.ver]);
         var _loc5_:IEventDispatcher = _loc2_ as IEventDispatcher;
         _loc5_.addEventListener(Event.COMPLETE,this.done);
         _loc5_.addEventListener(IOErrorEvent.IO_ERROR,this.eee);
         _loc5_.addEventListener(ProgressEvent.PROGRESS,this.dllprogress);
      }
      
      private function eee(param1:Event = null) : void
      {
         var _loc2_:String = "加载文件失败，请清除浏览器缓存后重新进入游戏！";
         addChildAt(this.txt,0);
         this.txt.text = _loc2_;
         if(ExternalInterface.available)
         {
            ExternalInterface.call("returnPage",_loc2_);
         }
      }
      
      private function done(param1:Event) : void
      {
         removeChild(this.txt);
      }
      
      private function dllprogress(param1:ProgressEvent) : void
      {
         var _loc2_:int = param1.bytesLoaded / param1.bytesTotal * 100;
         this.txt.text = "Loading " + _loc2_ + "%";
      }
   }
}

RFPluginUtils;

