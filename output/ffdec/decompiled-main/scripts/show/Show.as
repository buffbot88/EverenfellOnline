package show
{
   import com.youbt.manager.RFSystemManager;
   import flash.display.DisplayObject;
   import flash.display.Sprite;
   import flash.display.Stage;
   import flash.events.Event;
   import flash.text.TextField;
   
   public class Show extends Sprite
   {
      
      public var current:DisplayObject;
      
      public function Show(param1:TextField)
      {
         var _loc4_:ShowObj = null;
         super();
         RFSystemManager.getInstance().addEventListener("cl",this.removeAll);
         var _loc2_:String = "l/0.jpg";
         var _loc3_:Stage = RFSystemManager.getInstance().stage;
         _loc4_ = new ShowObj(_loc2_,this,_loc4_,param1);
      }
      
      public function removeAll(param1:Event) : void
      {
         RFSystemManager.getInstance().removeEventListener("cl",this.removeAll);
         if(this.parent)
         {
            this.parent.removeChild(this);
         }
         while(this.numChildren > 0)
         {
            this.removeChildAt(0);
         }
      }
   }
}

