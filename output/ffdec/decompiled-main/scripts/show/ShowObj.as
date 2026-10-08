package show
{
   import com.youbt.manager.RFSystemManager;
   import flash.display.Bitmap;
   import flash.display.BitmapData;
   import flash.display.Graphics;
   import flash.display.Shape;
   import flash.display.Stage;
   import flash.events.Event;
   import flash.events.IEventDispatcher;
   import flash.events.IOErrorEvent;
   import flash.text.TextField;
   
   public class ShowObj
   {
      
      private var txt:TextField;
      
      private var url:String;
      
      public var n:ShowObj;
      
      private var p:Show;
      
      public var r:Boolean;
      
      public var t:int = 0;
      
      private var loader:Shape;
      
      public function ShowObj(param1:String, param2:Show, param3:ShowObj, param4:TextField)
      {
         super();
         this.url = param1;
         this.p = param2;
         this.txt = param4;
         if(param3)
         {
            param3.n = this;
         }
         else
         {
            this.l();
         }
         this.er();
      }
      
      public function l() : void
      {
         this.c(null);
      }
      
      private function c(param1:Event) : void
      {
         if(this.n)
         {
            this.n.l();
         }
         RFSystemManager.getInstance().stage.addEventListener(Event.RESIZE,this.er);
         this.d();
      }
      
      private function er(param1:Event = null) : void
      {
         var _loc2_:Stage = RFSystemManager.getInstance().stage;
         if(this.loader)
         {
            this.loader.x = (_loc2_.stageWidth - this.loader.width) / 2;
            this.loader.y = (_loc2_.stageHeight - this.loader.height) / 2;
            this.txt.y = this.loader.y + this.loader.height + 15;
         }
         else
         {
            this.txt.y = _loc2_.stage.height / 2;
         }
         this.txt.width = _loc2_.stageWidth;
      }
      
      private function d(param1:Event = null) : void
      {
         this.r = true;
         if(!this.loader)
         {
            this.loader = new Shape();
         }
         var _loc2_:Graphics = this.loader.graphics;
         var _loc3_:Bitmap = new Bitmap(new BitmapData(100,100,true,0));
         var _loc4_:BitmapData = _loc3_.bitmapData;
         _loc2_.clear();
         _loc2_.beginBitmapFill(_loc4_);
         _loc2_.drawRect(0,0,_loc4_.width,_loc4_.height);
         _loc2_.endFill();
         this.er();
         this.loader.visible = false;
         this.loader.addEventListener(Event.REMOVED_FROM_STAGE,this.dispose);
         this.loader.addEventListener(Event.ENTER_FRAME,this.eh);
         this.loader.alpha = 0;
         this.p.addChild(this.loader);
      }
      
      private function eh(param1:Event) : void
      {
         if(this.p.current == null)
         {
            this.p.current = this.loader;
            this.loader.visible = true;
         }
         else if(this.p.current == this.loader)
         {
            if(this.t < 61)
            {
               this.loader.alpha = this.t / 60;
               ++this.t;
            }
            else if(this.t > 60 && this.t < 90)
            {
               ++this.t;
            }
            else
            {
               if(this.n)
               {
                  if(this.t >= 90 && this.t < 120 && this.n.r)
                  {
                     this.loader.alpha = (120 - this.t) / 30;
                  }
                  else if(this.t >= 120)
                  {
                     this.dispose();
                  }
               }
               else if(this.t >= 240)
               {
                  this.p.graphics.clear();
               }
               ++this.t;
            }
         }
      }
      
      private function error(param1:IOErrorEvent) : void
      {
         var _loc2_:IEventDispatcher = param1.currentTarget as IEventDispatcher;
         _loc2_.removeEventListener(Event.COMPLETE,this.c);
         _loc2_.removeEventListener(Event.COMPLETE,this.d);
         _loc2_.removeEventListener(IOErrorEvent.IO_ERROR,this.error);
         this.dispose();
      }
      
      public function dispose(param1:Event = null) : void
      {
         if(this.p)
         {
            this.p.current = null;
         }
         this.p = null;
         this.n = null;
         if(this.loader)
         {
            this.loader.removeEventListener(Event.ENTER_FRAME,this.eh);
            this.loader.removeEventListener(Event.REMOVED_FROM_STAGE,this.dispose);
            if(this.loader.parent)
            {
               this.loader.parent.removeChild(this.loader);
            }
            this.loader = null;
         }
         this.txt = null;
         RFSystemManager.getInstance().stage.removeEventListener(Event.RESIZE,this.er);
      }
   }
}

