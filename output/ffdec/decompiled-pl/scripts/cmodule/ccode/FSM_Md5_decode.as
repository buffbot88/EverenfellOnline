package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   public final class FSM_Md5_decode extends Machine
   {
      
      public static const intRegCount:int = 6;
      
      public static const NumberRegCount:int = 0;
      
      public var i0:int;
      
      public var i1:int;
      
      public var i2:int;
      
      public var i3:int;
      
      public var i4:int;
      
      public var i5:int;
      
      public function FSM_Md5_decode()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:FSM_Md5_decode = null;
         _loc1_ = new FSM_Md5_decode();
         cmodule.ccode.gstate.gworker = _loc1_;
      }
      
      final override public function work() : void
      {
         switch(state)
         {
            case 0:
               mstate.esp -= 4;
               si32(mstate.ebp,mstate.esp);
               mstate.ebp = mstate.esp;
               mstate.esp -= 4;
               this.i0 = cmodule.ccode.__2E_str6105;
               mstate.esp -= 12;
               this.i1 = li32(mstate.ebp + 12);
               this.i2 = mstate.ebp + -4;
               si32(this.i1,mstate.esp);
               si32(this.i0,mstate.esp + 4);
               si32(this.i2,mstate.esp + 8);
               state = 1;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_ArrayValue]();
               return;
            case 1:
               mstate.esp += 12;
               this.i0 = li32(mstate.ebp + -4);
               mstate.esp -= 8;
               this.i1 = cmodule.ccode.__2E_str7106;
               si32(this.i0,mstate.esp);
               si32(this.i1,mstate.esp + 4);
               state = 2;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
            case 2:
               this.i0 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 4;
               si32(this.i0,mstate.esp);
               state = 3;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_IntValue]();
               return;
            case 3:
               this.i0 = mstate.eax;
               mstate.esp += 4;
               this.i1 = li32(mstate.ebp + -4);
               mstate.esp -= 8;
               this.i2 = cmodule.ccode.__p_997;
               si32(this.i1,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 4;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
            case 4:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 4;
               si32(this.i2,mstate.esp);
               state = 5;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 5:
               mstate.esp += 4;
               mstate.esp -= 8;
               this.i2 = 0;
               si32(this.i2,mstate.esp);
               si32(this.i0,mstate.esp + 4);
               state = 6;
               mstate.esp -= 4;
               FSM_pubrealloc.start();
               return;
            case 6:
               this.i3 = mstate.eax;
               mstate.esp += 8;
               this.i4 = li32(cmodule.ccode.__p_10_E000);
               mstate.esp -= 12;
               this.i5 = cmodule.ccode.__p_775;
               si32(this.i1,mstate.esp);
               si32(this.i5,mstate.esp + 4);
               si32(this.i4,mstate.esp + 8);
               state = 7;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_SetS]();
               return;
            case 7:
               this.i4 = mstate.eax;
               mstate.esp += 12;
               mstate.esp -= 12;
               si32(this.i3,mstate.esp);
               si32(this.i1,mstate.esp + 4);
               si32(this.i0,mstate.esp + 8);
               state = 8;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_ByteArray_readBytes]();
               return;
            case 8:
               this.i1 = mstate.eax;
               mstate.esp += 12;
               mstate.esp -= 8;
               si32(this.i3,mstate.esp);
               si32(this.i0,mstate.esp + 4);
               state = 9;
               mstate.esp -= 4;
               FSM_MDByteArray.start();
               return;
            case 9:
               mstate.esp += 8;
               this.i0 = li32(mstate.ebp + -4);
               mstate.esp -= 4;
               si32(this.i0,mstate.esp);
               state = 10;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 10:
               mstate.esp += 4;
               mstate.esp -= 8;
               si32(this.i3,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 11;
               mstate.esp -= 4;
               FSM_pubrealloc.start();
               return;
            case 11:
               this.i0 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 4;
               this.i0 = cmodule.ccode._output_2E_2595;
               si32(this.i0,mstate.esp);
               state = 12;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_String]();
               return;
            case 12:
               this.i1 = mstate.eax;
               mstate.esp += 4;
               mstate.esp -= 8;
               si32(this.i0,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 13;
               mstate.esp -= 4;
               FSM_pubrealloc.start();
               return;
            case 13:
               this.i0 = mstate.eax;
               mstate.esp += 8;
               mstate.eax = this.i1;
               mstate.esp = mstate.ebp;
               mstate.ebp = li32(mstate.esp);
               mstate.esp += 4;
               mstate.esp += 4;
               mstate.gworker = caller;
               return;
            default:
               throw "Invalid state in _Md5_decode";
         }
      }
   }
}

