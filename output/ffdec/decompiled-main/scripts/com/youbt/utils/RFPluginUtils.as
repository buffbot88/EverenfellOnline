package com.youbt.utils
{
   import flash.utils.ByteArray;
   
   public class RFPluginUtils
   {
      
      public static var decodeFunction:Function = de;
      
      public function RFPluginUtils()
      {
         super();
      }
      
      private static function de(param1:ByteArray) : ByteArray
      {
         var _loc5_:int = 0;
         var _loc6_:int = 0;
         var _loc2_:int = int(param1.length);
         var _loc3_:ByteArray = new ByteArray();
         var _loc4_:int = param1.readByte();
         if(_loc4_ >> 8)
         {
            _loc5_ = 0;
            loop0:
            while(_loc5_ < 10)
            {
               loop1:
               while(true)
               {
                  if(_loc5_ >> 1 & 1)
                  {
                     while(true)
                     {
                        if(param1.bytesAvailable)
                        {
                           break loop1;
                        }
                        if(!(_loc6_ & 1))
                        {
                        }
                        if(++_loc6_ >= _loc2_)
                        {
                           break;
                        }
                        _loc3_.writeInt(_loc6_ << 8);
                     }
                     continue;
                  }
                  _loc5_++;
                  continue loop0;
               }
               _loc4_ = param1.readByte();
               if(!(_loc4_ & 0xDD))
               {
                  if(_loc4_ & 0xCC)
                  {
                     return de(_loc3_);
                  }
               }
               param1.position += 3;
               break;
            }
         }
         else
         {
            _loc3_ = param1;
         }
         return _loc3_;
      }
   }
}

