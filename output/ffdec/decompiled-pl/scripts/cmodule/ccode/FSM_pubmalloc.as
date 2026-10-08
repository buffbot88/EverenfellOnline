package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   import avm2.intrinsics.memory.si8;
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   public final class FSM_pubmalloc extends Machine
   {
      
      public static const intRegCount:int = 18;
      
      public static const NumberRegCount:int = 0;
      
      public var i10:int;
      
      public var i11:int;
      
      public var i12:int;
      
      public var i13:int;
      
      public var i14:int;
      
      public var i15:int;
      
      public var i17:int;
      
      public var i16:int;
      
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
      
      public function FSM_pubmalloc()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:FSM_pubmalloc = null;
         _loc1_ = new FSM_pubmalloc();
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
               mstate.esp -= 32;
               this.i0 = cmodule.ccode.__2E_str58;
               mstate.esp -= 4;
               si32(this.i0,mstate.esp);
               state = 1;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Array]();
               return;
            case 1:
               this.i0 = mstate.eax;
               mstate.esp += 4;
               si32(this.i0,cmodule.ccode.__p_1E_003A);
               mstate.esp -= 4;
               this.i0 = 0;
               si32(this.i0,mstate.esp);
               state = 2;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Int]();
               return;
            case 2:
               this.i1 = mstate.eax;
               mstate.esp += 4;
               si32(this.i1,cmodule.ccode.__p_10_E000);
               this.i1 = mstate.ebp + -16;
               this.i2 = cmodule.ccode.__2E_str1100;
               this.i3 = 12;
               cmodule.ccode.memcpy(this.i1,this.i2,this.i3);
               this.i2 = 102;
               si8(this.i2,mstate.ebp + -16);
               this.i3 = 108;
               si8(this.i3,mstate.ebp + -15);
               this.i4 = 97;
               si8(this.i4,mstate.ebp + -14);
               this.i5 = 115;
               si8(this.i5,mstate.ebp + -13);
               this.i6 = 104;
               si8(this.i6,mstate.ebp + -12);
               this.i7 = 46;
               si8(this.i7,mstate.ebp + -11);
               this.i8 = 117;
               si8(this.i8,mstate.ebp + -10);
               this.i9 = 116;
               si8(this.i9,mstate.ebp + -9);
               this.i10 = 105;
               si8(this.i10,mstate.ebp + -8);
               si8(this.i3,mstate.ebp + -7);
               si8(this.i5,mstate.ebp + -6);
               mstate.esp -= 4;
               si32(this.i1,mstate.esp);
               state = 3;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_String]();
               return;
            case 3:
               this.i1 = mstate.eax;
               mstate.esp += 4;
               this.i11 = mstate.ebp + -32;
               this.i12 = cmodule.ccode.__2E_str2101;
               this.i13 = 10;
               cmodule.ccode.memcpy(this.i11,this.i12,this.i13);
               this.i12 = 66;
               si8(this.i12,mstate.ebp + -32);
               this.i12 = 121;
               si8(this.i12,mstate.ebp + -31);
               si8(this.i9,mstate.ebp + -30);
               this.i13 = 101;
               si8(this.i13,mstate.ebp + -29);
               this.i14 = 65;
               si8(this.i14,mstate.ebp + -28);
               this.i14 = 114;
               si8(this.i14,mstate.ebp + -27);
               si8(this.i14,mstate.ebp + -26);
               si8(this.i4,mstate.ebp + -25);
               si8(this.i12,mstate.ebp + -24);
               mstate.esp -= 8;
               si32(this.i1,mstate.esp);
               si32(this.i11,mstate.esp + 4);
               state = 4;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_NSGetS]();
               return;
            case 4:
               this.i1 = mstate.eax;
               mstate.esp += 8;
               si32(this.i1,cmodule.ccode.__p_A0_7711);
               si8(this.i3,cmodule.ccode.__p_997);
               si8(this.i13,cmodule.ccode.__p_997 + 1);
               this.i1 = 110;
               si8(this.i1,cmodule.ccode.__p_997 + 2);
               this.i11 = 103;
               si8(this.i11,cmodule.ccode.__p_997 + 3);
               si8(this.i9,cmodule.ccode.__p_997 + 4);
               si8(this.i6,cmodule.ccode.__p_997 + 5);
               this.i6 = 112;
               si8(this.i6,cmodule.ccode.__p_775);
               this.i6 = 111;
               si8(this.i6,cmodule.ccode.__p_775 + 1);
               si8(this.i5,cmodule.ccode.__p_775 + 2);
               si8(this.i10,cmodule.ccode.__p_775 + 3);
               si8(this.i9,cmodule.ccode.__p_775 + 4);
               si8(this.i10,cmodule.ccode.__p_775 + 5);
               si8(this.i6,cmodule.ccode.__p_775 + 6);
               si8(this.i1,cmodule.ccode.__p_775 + 7);
               this.i15 = 100;
               si8(this.i15,cmodule.ccode.__p_81);
               si8(this.i13,cmodule.ccode.__p_81 + 1);
               this.i16 = 99;
               si8(this.i16,cmodule.ccode.__p_81 + 2);
               si8(this.i6,cmodule.ccode.__p_81 + 3);
               si8(this.i15,cmodule.ccode.__p_81 + 4);
               si8(this.i13,cmodule.ccode.__p_81 + 5);
               this.i17 = 70;
               si8(this.i17,cmodule.ccode.__p_81 + 6);
               si8(this.i8,cmodule.ccode.__p_81 + 7);
               si8(this.i1,cmodule.ccode.__p_81 + 8);
               si8(this.i16,cmodule.ccode.__p_81 + 9);
               si8(this.i9,cmodule.ccode.__p_81 + 10);
               si8(this.i10,cmodule.ccode.__p_81 + 11);
               si8(this.i6,cmodule.ccode.__p_81 + 12);
               si8(this.i1,cmodule.ccode.__p_81 + 13);
               si8(this.i16,cmodule.ccode.__p_50);
               si8(this.i6,cmodule.ccode.__p_50 + 1);
               this.i16 = 109;
               si8(this.i16,cmodule.ccode.__p_50 + 2);
               si8(this.i7,cmodule.ccode.__p_50 + 3);
               si8(this.i12,cmodule.ccode.__p_50 + 4);
               si8(this.i6,cmodule.ccode.__p_50 + 5);
               si8(this.i8,cmodule.ccode.__p_50 + 6);
               this.i16 = 98;
               si8(this.i16,cmodule.ccode.__p_50 + 7);
               si8(this.i9,cmodule.ccode.__p_50 + 8);
               si8(this.i7,cmodule.ccode.__p_50 + 9);
               si8(this.i8,cmodule.ccode.__p_50 + 10);
               si8(this.i9,cmodule.ccode.__p_50 + 11);
               si8(this.i10,cmodule.ccode.__p_50 + 12);
               si8(this.i3,cmodule.ccode.__p_50 + 13);
               si8(this.i5,cmodule.ccode.__p_50 + 14);
               this.i7 = 82;
               si8(this.i7,cmodule.ccode.__p_454);
               si8(this.i17,cmodule.ccode.__p_454 + 1);
               this.i7 = 80;
               si8(this.i7,cmodule.ccode.__p_454 + 2);
               si8(this.i3,cmodule.ccode.__p_454 + 3);
               si8(this.i8,cmodule.ccode.__p_454 + 4);
               si8(this.i11,cmodule.ccode.__p_454 + 5);
               si8(this.i10,cmodule.ccode.__p_454 + 6);
               si8(this.i1,cmodule.ccode.__p_454 + 7);
               this.i7 = 85;
               si8(this.i7,cmodule.ccode.__p_454 + 8);
               si8(this.i9,cmodule.ccode.__p_454 + 9);
               si8(this.i10,cmodule.ccode.__p_454 + 10);
               si8(this.i3,cmodule.ccode.__p_454 + 11);
               si8(this.i5,cmodule.ccode.__p_454 + 12);
               si8(this.i16,cmodule.ccode.__p_42);
               si8(this.i12,cmodule.ccode.__p_42 + 1);
               si8(this.i9,cmodule.ccode.__p_42 + 2);
               si8(this.i13,cmodule.ccode.__p_42 + 3);
               si8(this.i5,cmodule.ccode.__p_42 + 4);
               si8(this.i5,cmodule.ccode.__p_614);
               si8(this.i9,cmodule.ccode.__p_614 + 1);
               si8(this.i4,cmodule.ccode.__p_614 + 2);
               si8(this.i11,cmodule.ccode.__p_614 + 3);
               si8(this.i13,cmodule.ccode.__p_614 + 4);
               si8(this.i3,cmodule.ccode.__p_982);
               si8(this.i6,cmodule.ccode.__p_982 + 1);
               si8(this.i4,cmodule.ccode.__p_982 + 2);
               si8(this.i15,cmodule.ccode.__p_982 + 3);
               si8(this.i13,cmodule.ccode.__p_982 + 4);
               si8(this.i14,cmodule.ccode.__p_982 + 5);
               this.i4 = 73;
               si8(this.i4,cmodule.ccode.__p_982 + 6);
               si8(this.i1,cmodule.ccode.__p_982 + 7);
               si8(this.i2,cmodule.ccode.__p_982 + 8);
               si8(this.i6,cmodule.ccode.__p_982 + 9);
               si8(this.i8,cmodule.ccode.__p_90);
               si8(this.i14,cmodule.ccode.__p_90 + 1);
               si8(this.i3,cmodule.ccode.__p_90 + 2);
               si8(this.i2,cmodule.ccode.__p_885);
               si8(this.i10,cmodule.ccode.__p_885 + 1);
               si8(this.i3,cmodule.ccode.__p_885 + 2);
               si8(this.i13,cmodule.ccode.__p_885 + 3);
               this.i1 = 58;
               si8(this.i1,cmodule.ccode.__p_885 + 4);
               this.i1 = 47;
               si8(this.i1,cmodule.ccode.__p_885 + 5);
               si8(this.i1,cmodule.ccode.__p_885 + 6);
               si8(this.i1,cmodule.ccode.__p_885 + 7);
               mstate.esp -= 12;
               this.i1 = li32(mstate.ebp + 12);
               this.i2 = cmodule.ccode.__2E_str3102;
               this.i3 = cmodule.ccode.___2E_p06872;
               si32(this.i1,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               si32(this.i3,mstate.esp + 8);
               state = 5;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_ArrayValue]();
               return;
            case 5:
               mstate.esp += 12;
               mstate.esp -= 8;
               this.i1 = cmodule.ccode._irealloc;
               si32(this.i0,mstate.esp);
               si32(this.i1,mstate.esp + 4);
               state = 6;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Function]();
               return;
            case 6:
               this.i0 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 4;
               this.i1 = cmodule.ccode.__p_50;
               si32(this.i1,mstate.esp);
               state = 7;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_String]();
               return;
            case 7:
               this.i1 = mstate.eax;
               mstate.esp += 4;
               mstate.esp -= 8;
               this.i2 = cmodule.ccode.__p_454;
               si32(this.i1,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 8;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_NSGetS]();
               return;
            case 8:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               si32(this.i2,cmodule.ccode.___2E_p10662);
               mstate.esp -= 4;
               si32(this.i1,mstate.esp);
               state = 9;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 9:
               mstate.esp += 4;
               this.i1 = li32(cmodule.ccode.___2E_p10662);
               mstate.esp -= 8;
               this.i2 = cmodule.ccode.__p_81;
               si32(this.i1,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 10;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_GetS]();
               return;
            case 10:
               this.i1 = mstate.eax;
               mstate.esp += 8;
               si32(this.i1,cmodule.ccode.___2E_p73862);
               this.i1 = li32(cmodule.ccode.___2E_p10662);
               mstate.esp -= 12;
               si32(this.i1,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               si32(this.i0,mstate.esp + 8);
               state = 11;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_SetS]();
               return;
            case 11:
               this.i1 = mstate.eax;
               mstate.esp += 12;
               mstate.esp -= 4;
               si32(this.i0,mstate.esp);
               state = 12;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Release]();
               return;
            case 12:
               mstate.esp += 4;
               state = 13;
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode._AS3_Null]();
               return;
            case 13:
               this.i0 = mstate.eax;
               mstate.eax = this.i0;
               mstate.esp = mstate.ebp;
               mstate.ebp = li32(mstate.esp);
               mstate.esp += 4;
               mstate.esp += 4;
               mstate.gworker = caller;
               return;
            default:
               throw "Invalid state in _pubmalloc";
         }
      }
   }
}

