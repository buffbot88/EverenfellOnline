package
{
   import cmodule.ccode.CLibInit;
   import flash.display.Sprite;
   
   [SWF(width="1", height="1", backgroundColor="#191b1e", frameRate="30")]
   public class PlatformLoader extends Sprite
   {
      
      private static var _:Boolean = true;
      
      public function PlatformLoader()
      {
         super();
         if(_)
         {
            new CLibInit().init().$(this);
            _ = false;
         }
      }
   }
}

