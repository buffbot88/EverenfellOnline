package
{
   import com.youbt.utils.RFPluginUtils;
   import flash.display.Loader;
   import flash.display.Sprite;
   import flash.events.Event;
   import flash.events.IEventDispatcher;
   import flash.events.IOErrorEvent;
   import flash.events.ProgressEvent;
   import flash.events.SecurityErrorEvent;
   import flash.net.URLRequest;
   import flash.net.URLStream;
   import flash.utils.ByteArray;
   
   [SWF(width="1", height="1", backgroundColor="#000000", frameRate="4")]
   [SWF(frameRate="4",backgroundColor="#000000",width="1",height="1")]
   public final class EnLoader extends Sprite
   {
      
      private var _l:Array;
      
      public function EnLoader()
      {
         super();
      }
      
      public function r(a:Array) : void
      {
         this._l = a;
         this.ld();
      }
      
      private function ld(e:Event = null) : void
      {
         var l:IEventDispatcher = null;
         var s:URLStream = null;
         if(Boolean(e))
         {
            l = e.currentTarget as IEventDispatcher;
            l.removeEventListener(Event.COMPLETE,this.ld);
            l.removeEventListener(IOErrorEvent.IO_ERROR,this.l);
            l.removeEventListener(ProgressEvent.PROGRESS,this.p);
         }
         if(Boolean(this._l) && this._l.length > 0)
         {
            s = new URLStream();
            s.addEventListener(Event.COMPLETE,this.c);
            s.addEventListener(IOErrorEvent.IO_ERROR,this.l);
            s.addEventListener(SecurityErrorEvent.SECURITY_ERROR,this.l);
            s.addEventListener(ProgressEvent.PROGRESS,this.p);
            s.load(new URLRequest(this._l.pop()));
         }
         else
         {
            this.dispatchEvent(new Event(Event.COMPLETE));
            if(Boolean(this.loaderInfo.loader))
            {
               this.loaderInfo.loader.unloadAndStop();
            }
         }
      }
      
      private function p(e:ProgressEvent) : void
      {
         this.dispatchEvent(e);
      }
      
      private function l(e:Event) : void
      {
         var c:IEventDispatcher = e.currentTarget as IEventDispatcher;
         c.removeEventListener(IOErrorEvent.IO_ERROR,this.l);
         c.removeEventListener(SecurityErrorEvent.SECURITY_ERROR,this.l);
         c.removeEventListener(ProgressEvent.PROGRESS,this.p);
         this.dispatchEvent(e);
      }
      
      private function c(e:Event) : void
      {
         var s:URLStream = e.currentTarget as URLStream;
         s.removeEventListener(IOErrorEvent.IO_ERROR,this.l);
         s.removeEventListener(SecurityErrorEvent.SECURITY_ERROR,this.l);
         s.removeEventListener(ProgressEvent.PROGRESS,this.p);
         var l:ByteArray = new ByteArray();
         s.readBytes(l);
         l = RFPluginUtils.decodeFunction(l);
         var ld:Loader = new Loader();
         ld.contentLoaderInfo.addEventListener(Event.COMPLETE,this.ld);
         ld.contentLoaderInfo.addEventListener(IOErrorEvent.IO_ERROR,this.l);
         ld.loadBytes(l);
      }
   }
}

