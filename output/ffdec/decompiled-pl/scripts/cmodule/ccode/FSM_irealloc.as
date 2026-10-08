package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.li8;
   import avm2.intrinsics.memory.si32;
   import avm2.intrinsics.memory.si8;
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   public final class FSM_irealloc extends Machine
   {
      
      public static const intRegCount:int = 12;
      
      public static const NumberRegCount:int = 0;
      
      public var i10:int;
      
      public var i11:int;
      
      public var i0:int;
      
      public var i1:int;
      
      public var i2:int;
      
      public var i3:int;
      
      public var i4:int;
      
      public var i5:int;
      
      public var i6:int;
      
      public var i7:int;
      
      public var i8:int;
      
      public var i9:int;
      
      public function FSM_irealloc()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:FSM_irealloc = null;
         _loc1_ = new FSM_irealloc();
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
               this.i0 = cmodule.ccode.__p_81;
               this.i1 = li32(cmodule.ccode.___2E_p73862);
               this.i2 = li32(cmodule.ccode.___2E_p10662);
               mstate.esp -= 12;
               si32(this.i2,mstate.esp);
               si32(this.i0,mstate.esp + 4);
               si32(this.i1,mstate.esp + 8);
               state = 1;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_SetS]();
               return;
            case 1:
               this.i0 = mstate.eax;
               mstate.esp += 12;
               this.i0 = li32(cmodule.ccode.___2E_p10662);
               mstate.esp -= 4;
               si32(this.i0,mstate.esp);
               state = 2;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 2:
               mstate.esp += 4;
               mstate.esp -= 12;
               this.i0 = li32(mstate.ebp + 12);
               this.i1 = cmodule.ccode.__2E_str6105;
               this.i2 = mstate.ebp + -4;
               si32(this.i0,mstate.esp);
               si32(this.i1,mstate.esp + 4);
               si32(this.i2,mstate.esp + 8);
               state = 3;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_ArrayValue]();
               return;
            case 3:
               mstate.esp += 12;
               this.i0 = li32(mstate.ebp + -4);
               mstate.esp -= 8;
               this.i1 = cmodule.ccode.__p_997;
               si32(this.i0,mstate.esp);
               si32(this.i1,mstate.esp + 4);
               state = 4;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
            case 4:
               this.i0 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 4;
               si32(this.i0,mstate.esp);
               state = 5;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_IntValue]();
               return;
            case 5:
               this.i0 = mstate.eax;
               mstate.esp += 4;
               this.i2 = li32(mstate.ebp + -4);
               mstate.esp -= 8;
               si32(this.i2,mstate.esp);
               si32(this.i1,mstate.esp + 4);
               state = 6;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
            case 6:
               this.i1 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 4;
               si32(this.i1,mstate.esp);
               state = 7;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 7:
               mstate.esp += 4;
               mstate.esp -= 8;
               this.i1 = 0;
               si32(this.i1,mstate.esp);
               si32(this.i0,mstate.esp + 4);
               state = 8;
               mstate.esp -= 4;
               FSM_pubrealloc.start();
               return;
            case 8:
               this.i1 = mstate.eax;
               mstate.esp += 8;
               this.i3 = li32(cmodule.ccode.__p_10_E000);
               mstate.esp -= 12;
               this.i4 = cmodule.ccode.__p_775;
               si32(this.i2,mstate.esp);
               si32(this.i4,mstate.esp + 4);
               si32(this.i3,mstate.esp + 8);
               state = 9;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_SetS]();
               return;
            case 9:
               this.i3 = mstate.eax;
               mstate.esp += 12;
               mstate.esp -= 12;
               si32(this.i1,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               si32(this.i0,mstate.esp + 8);
               state = 10;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_ByteArray_readBytes]();
               return;
            case 10:
               this.i2 = mstate.eax;
               mstate.esp += 12;
               this.i2 = li32(mstate.ebp + -4);
               mstate.esp -= 4;
               si32(this.i2,mstate.esp);
               state = 11;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 11:
               mstate.esp += 4;
               this.i2 = li32(cmodule.ccode.___2E_p06872);
               mstate.esp -= 8;
               this.i3 = cmodule.ccode.__p_614;
               si32(this.i2,mstate.esp);
               si32(this.i3,mstate.esp + 4);
               state = 12;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
            case 12:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 8;
               this.i3 = cmodule.ccode.__p_982;
               si32(this.i2,mstate.esp);
               si32(this.i3,mstate.esp + 4);
               state = 13;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
            case 13:
               this.i3 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 4;
               si32(this.i2,mstate.esp);
               state = 14;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 14:
               mstate.esp += 4;
               mstate.esp -= 8;
               this.i2 = cmodule.ccode.__p_90;
               si32(this.i3,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 15;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
            case 15:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 4;
               si32(this.i2,mstate.esp);
               state = 16;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_StringValue]();
               return;
            case 16:
               this.i4 = mstate.eax;
               mstate.esp += 4;
               mstate.esp -= 4;
               si32(this.i2,mstate.esp);
               state = 17;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 17:
               mstate.esp += 4;
               mstate.esp -= 8;
               this.i2 = cmodule.ccode.__p_885;
               si32(this.i4,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               mstate.esp -= 4;
               FSM_strstr.start();
            case 18:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               this.i4 = this.i1;
               if(this.i2 != 0)
               {
                  this.i0 = 0;
                  break;
               }
               this.i2 = cmodule.ccode.__p_42;
               mstate.esp -= 8;
               si32(this.i3,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 19;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
               break;
            case 19:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 8;
               this.i5 = cmodule.ccode.__p_997;
               si32(this.i2,mstate.esp);
               si32(this.i5,mstate.esp + 4);
               state = 20;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
            case 20:
               this.i6 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 4;
               si32(this.i6,mstate.esp);
               state = 21;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_IntValue]();
               return;
            case 21:
               this.i6 = mstate.eax;
               mstate.esp += 4;
               mstate.esp -= 8;
               si32(this.i2,mstate.esp);
               si32(this.i5,mstate.esp + 4);
               state = 22;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
            case 22:
               this.i5 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 4;
               si32(this.i5,mstate.esp);
               state = 23;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 23:
               mstate.esp += 4;
               mstate.esp -= 8;
               this.i5 = 0;
               si32(this.i5,mstate.esp);
               si32(this.i6,mstate.esp + 4);
               state = 24;
               mstate.esp -= 4;
               FSM_pubrealloc.start();
               return;
            case 24:
               this.i7 = mstate.eax;
               mstate.esp += 8;
               this.i8 = li32(cmodule.ccode.__p_10_E000);
               mstate.esp -= 12;
               this.i9 = cmodule.ccode.__p_775;
               si32(this.i2,mstate.esp);
               si32(this.i9,mstate.esp + 4);
               si32(this.i8,mstate.esp + 8);
               state = 25;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_SetS]();
               return;
            case 25:
               this.i8 = mstate.eax;
               mstate.esp += 12;
               mstate.esp -= 12;
               si32(this.i7,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               si32(this.i6,mstate.esp + 8);
               state = 26;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_ByteArray_readBytes]();
               return;
            case 26:
               this.i8 = mstate.eax;
               mstate.esp += 12;
               mstate.esp -= 4;
               si32(this.i2,mstate.esp);
               state = 27;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 27:
               mstate.esp += 4;
               mstate.esp -= 8;
               si32(this.i7,mstate.esp);
               si32(this.i6,mstate.esp + 4);
               state = 28;
               mstate.esp -= 4;
               FSM_MDByteArray.start();
               return;
            case 28:
               mstate.esp += 8;
               mstate.esp -= 4;
               si32(this.i3,mstate.esp);
               state = 29;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 29:
               mstate.esp += 4;
               this.i2 = li8(this.i1);
               this.i3 = this.i2 + 32;
               si32(this.i3,cmodule.ccode.___2E_i76112);
               mstate.esp -= 8;
               si32(this.i5,mstate.esp);
               si32(this.i3,mstate.esp + 4);
               state = 30;
               mstate.esp -= 4;
               FSM_pubrealloc.start();
               return;
            case 30:
               this.i3 = mstate.eax;
               mstate.esp += 8;
               si32(this.i3,cmodule.ccode.___2E_str87531);
               si32(this.i3,cmodule.ccode.___2E_str75132);
               this.i5 = this.i2;
               if(this.i2 <= 0)
               {
                  this.i6 = this.i3;
                  this.i7 = this.i3;
               }
               else
               {
                  this.i6 = 0;
                  this.i7 = this.i3;
                  this.i8 = this.i3;
                  while(true)
                  {
                     this.i9 = this.i4 + this.i6;
                     this.i9 = li8(this.i9 + 1);
                     si8(this.i9,this.i8);
                     this.i6 += 1;
                     this.i8 = this.i7 + 1;
                     if(this.i6 == this.i2)
                     {
                        break;
                     }
                     this.i7 = this.i8;
                  }
                  si32(this.i8,cmodule.ccode.___2E_str87531);
                  this.i6 = this.i8;
                  this.i7 = this.i8;
               }
               this.i8 = cmodule.ccode._output_2E_2595;
               this.i9 = 0;
               while(true)
               {
                  this.i10 = this.i8 + this.i9;
                  this.i10 = li8(this.i10);
                  si8(this.i10,this.i7);
                  this.i7 = this.i9 + 1;
                  this.i10 = this.i6 + 1;
                  if(this.i7 == 32)
                  {
                     break;
                  }
                  this.i9 = this.i7;
                  this.i6 = this.i10;
                  this.i7 = this.i10;
               }
               this.i6 = 0;
               si32(this.i3,cmodule.ccode.___2E_str87531);
               this.i0 -= this.i2;
               mstate.esp -= 8;
               this.i2 = this.i0 + -4;
               si32(this.i6,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 31;
               mstate.esp -= 4;
               FSM_pubrealloc.start();
               return;
            case 31:
               this.i6 = mstate.eax;
               mstate.esp += 8;
               si32(this.i2,cmodule.ccode.___2E_i86002);
               this.i2 = this.i6;
               if(this.i0 == 4)
               {
                  this.i2 = this.i3;
                  this.i3 = this.i6;
               }
               else
               {
                  this.i7 = 0;
                  this.i8 = li32(cmodule.ccode.___2E_i76112);
                  this.i5 &= 255;
                  this.i4 += this.i5;
                  this.i5 = this.i3 + this.i8;
                  this.i8 = this.i0 + -5;
                  this.i9 = this.i3;
                  while(true)
                  {
                     this.i10 = this.i4 + this.i7;
                     this.i10 = li8(this.i10 + 1);
                     this.i11 = li8(this.i9);
                     this.i10 -= this.i11;
                     this.i11 = this.i2 + this.i7;
                     this.i9 += 1;
                     si8(this.i10,this.i11);
                     this.i10 = this.i5 == this.i9 ? this.i3 : this.i9;
                     this.i11 = this.i7 + 1;
                     if(this.i8 == this.i7)
                     {
                        break;
                     }
                     this.i7 = this.i11;
                     this.i9 = this.i10;
                  }
                  this.i2 = this.i5 == this.i9 ? this.i3 : this.i9;
                  si32(this.i2,cmodule.ccode.___2E_str87531);
                  this.i3 = this.i6 + this.i11;
                  this.i2 = this.i10;
               }
               this.i4 = 0;
               mstate.esp -= 8;
               si32(this.i2,mstate.esp);
               si32(this.i4,mstate.esp + 4);
               state = 32;
               mstate.esp -= 4;
               FSM_pubrealloc.start();
               return;
            case 32:
               this.i2 = mstate.eax;
               this.i0 = 4 - this.i0;
               mstate.esp += 8;
               this.i0 = this.i3 + this.i0;
               break;
            case 33:
               this.i4 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 12;
               si32(this.i4,mstate.esp);
               si32(this.i0,mstate.esp + 4);
               si32(this.i3,mstate.esp + 8);
               state = 34;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_ByteArray_writeBytes]();
               return;
            case 34:
               this.i0 = mstate.eax;
               mstate.esp += 12;
               mstate.esp -= 8;
               si32(this.i1,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 35;
               mstate.esp -= 4;
               FSM_pubrealloc.start();
               return;
            case 35:
               this.i0 = mstate.eax;
               mstate.esp += 8;
               mstate.eax = this.i4;
               mstate.esp = mstate.ebp;
               mstate.ebp = li32(mstate.esp);
               mstate.esp += 4;
               mstate.esp += 4;
               mstate.gworker = caller;
               return;
            default:
               throw "Invalid state in _irealloc";
         }
         this.i2 = 0;
         this.i3 = li32(cmodule.ccode.___2E_i86002);
         this.i4 = li32(cmodule.ccode.__p_1E_003A);
         this.i5 = li32(cmodule.ccode.__p_A0_7711);
         mstate.esp -= 8;
         si32(this.i5,mstate.esp);
         si32(this.i4,mstate.esp + 4);
         state = 33;
         mstate.esp -= 4;
         mstate.funcs[cmodule.ccode._AS3_New]();
      }
   }
}

