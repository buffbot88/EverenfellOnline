package com.youbt.core
{
   import com.youbt.utils.NameUtil;
   import flash.display.Sprite;
   
   public class RFSprite extends Sprite
   {
      
      public function RFSprite()
      {
         super();
         try
         {
            name = NameUtil.createUniqueName(this);
         }
         catch(e:Error)
         {
         }
      }
      
      override public function toString() : String
      {
         return NameUtil.displayObjectToString(this);
      }
   }
}

