package cmodule.ccode
{
   import flash.display.Sprite;
   
   public class ConSprite extends Sprite
   {
      
      private var runner:CRunner = new CRunner();
      
      public function ConSprite()
      {
         super();
         if(cmodule.ccode.gsprite)
         {
            cmodule.ccode.log(1,"More than one sprite!");
         }
         cmodule.ccode.gsprite = this;
         this.runner.startSystem();
      }
   }
}

