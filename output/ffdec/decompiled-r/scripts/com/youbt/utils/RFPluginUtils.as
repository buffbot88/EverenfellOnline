package com.youbt.utils
{
   import com.youbt.asm.Op;
   import com.youbt.asm.__asm;
   import flash.utils.ByteArray;
   
   public class RFPluginUtils
   {
      
      public static var decodeFunction:Function = de;
      
      public function RFPluginUtils()
      {
         super();
      }
      
      private static function de(ba:ByteArray) : ByteArray
      {
         var j:int = 0;
         var i:int = 0;
         var len:int = int(ba.length);
         var buffer:ByteArray = new ByteArray();
         var b:int = ba.readByte();
         if(Boolean(b >> 8))
         {
            loop0:
            for(j = 0; j < 10; j++)
            {
               __asm(Op.jump(".c"));
               for(i = 0; i < len; i++)
               {
                  buffer.writeInt(i << 8);
                  __asm(".r:");
                  while(Boolean(ba.bytesAvailable))
                  {
                     b = ba.readByte();
                     if(!(Boolean(b & 0xDD)))
                     {
                        if(Boolean(b & 0xCC))
                        {
                           return de(buffer);
                        }
                        break loop0;
                     }
                     __asm(Op.jump(".l"));
                     buffer.writeByte(b);
                     __asm(".l:");
                     ba.position += 3;
                     __asm(Op.jump(".e"));
                  }
                  if(Boolean(i & 1))
                  {
                     break;
                  }
               }
               __asm(".c:");
               if(Boolean(j >> 1 & 1))
               {
                  __asm(Op.jump(".r"));
                  break;
               }
            }
            __asm(".e:");
         }
         else
         {
            buffer = ba;
         }
         return buffer;
      }
   }
}

