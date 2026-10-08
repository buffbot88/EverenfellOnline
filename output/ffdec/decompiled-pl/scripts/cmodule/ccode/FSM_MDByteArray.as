package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.li8;
   import avm2.intrinsics.memory.si32;
   import avm2.intrinsics.memory.si8;
   
   public final class FSM_MDByteArray extends Machine
   {
      
      public static const intRegCount:int = 8;
      
      public static const NumberRegCount:int = 0;
      
      public var i0:int;
      
      public var i1:int;
      
      public var i2:int;
      
      public var i3:int;
      
      public var i4:int;
      
      public var i5:int;
      
      public var i6:int;
      
      public var i7:int;
      
      public function FSM_MDByteArray()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:FSM_MDByteArray = null;
         _loc1_ = new FSM_MDByteArray();
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
               mstate.esp -= 144;
               this.i0 = 0;
               si32(this.i0,mstate.ebp + -76);
               si32(this.i0,mstate.ebp + -80);
               this.i1 = 1732584193;
               si32(this.i1,mstate.ebp + -96);
               this.i1 = -271733879;
               si32(this.i1,mstate.ebp + -92);
               this.i1 = -1732584194;
               si32(this.i1,mstate.ebp + -88);
               this.i1 = 271733878;
               si32(this.i1,mstate.ebp + -84);
               mstate.esp -= 12;
               this.i1 = li32(mstate.ebp + 8);
               this.i2 = li32(mstate.ebp + 12);
               this.i3 = mstate.ebp + -96;
               si32(this.i3,mstate.esp);
               si32(this.i1,mstate.esp + 4);
               si32(this.i2,mstate.esp + 8);
               mstate.esp -= 4;
               FSM_md5update.start();
            case 1:
               mstate.esp += 12;
               this.i1 = li32(mstate.ebp + -80);
               si8(this.i1,mstate.ebp + -8);
               this.i2 = this.i1 >>> 8;
               si8(this.i2,mstate.ebp + -7);
               this.i2 = this.i1 >>> 16;
               si8(this.i2,mstate.ebp + -6);
               this.i2 = this.i1 >>> 24;
               si8(this.i2,mstate.ebp + -5);
               this.i2 = li32(mstate.ebp + -76);
               si8(this.i2,mstate.ebp + -4);
               this.i4 = this.i2 >>> 8;
               si8(this.i4,mstate.ebp + -3);
               this.i4 = this.i2 >>> 16;
               this.i1 >>>= 3;
               si8(this.i4,mstate.ebp + -2);
               this.i2 >>>= 24;
               si8(this.i2,mstate.ebp + -1);
               this.i1 &= 63;
               this.i2 = uint(this.i1) < uint(56) ? 56 : 120;
               mstate.esp -= 12;
               this.i4 = cmodule.ccode._PADDING;
               this.i1 = this.i2 - this.i1;
               si32(this.i3,mstate.esp);
               si32(this.i4,mstate.esp + 4);
               si32(this.i1,mstate.esp + 8);
               mstate.esp -= 4;
               FSM_md5update.start();
            case 2:
               mstate.esp += 12;
               mstate.esp -= 12;
               this.i1 = mstate.ebp + -8;
               this.i2 = 8;
               si32(this.i3,mstate.esp);
               si32(this.i1,mstate.esp + 4);
               si32(this.i2,mstate.esp + 8);
               mstate.esp -= 4;
               FSM_md5update.start();
            case 3:
               mstate.esp += 12;
               this.i1 = mstate.ebp + -144;
               this.i2 = mstate.ebp + -112;
               this.i4 = this.i0;
               do
               {
                  this.i5 = this.i3 + this.i4;
                  this.i5 = li32(this.i5);
                  this.i6 = this.i2 + this.i4;
                  si8(this.i5,this.i6);
                  this.i7 = this.i5 >>> 8;
                  si8(this.i7,this.i6 + 1);
                  this.i7 = this.i5 >>> 16;
                  si8(this.i7,this.i6 + 2);
                  this.i5 >>>= 24;
                  si8(this.i5,this.i6 + 3);
                  this.i4 += 4;
                  this.i0 += 1;
               }
               while(this.i0 != 4);
               this.i0 = 0;
               this.i3 = mstate.ebp + -96;
               do
               {
                  this.i4 = 0;
                  this.i5 = this.i3 + this.i0;
                  si8(this.i4,this.i5);
                  this.i0 += 1;
               }
               while(this.i0 != 88);
               this.i0 = 0;
               this.i3 = this.i1;
               break;
            case 4:
               mstate.esp += 12;
               this.i5 <<= 4;
               mstate.esp -= 12;
               this.i5 &= 240;
               this.i6 = this.i3 + 1;
               si32(this.i6,mstate.esp);
               si32(this.i4,mstate.esp + 4);
               si32(this.i5,mstate.esp + 8);
               state = 5;
               mstate.esp -= 4;
               FSM_sprintf.start();
               return;
            case 5:
               mstate.esp += 12;
               this.i3 += 2;
               this.i0 += 1;
               if(this.i0 != 16)
               {
                  break;
               }
               this.i0 = cmodule.ccode._output_2E_2595;
               this.i2 = 0;
               do
               {
                  this.i3 = this.i1 + this.i2;
                  this.i3 = li8(this.i3);
                  this.i4 = this.i0 + this.i2;
                  si8(this.i3,this.i4);
                  this.i2 += 1;
               }
               while(this.i2 != 32);
               mstate.esp = mstate.ebp;
               mstate.ebp = li32(mstate.esp);
               mstate.esp += 4;
               mstate.esp += 4;
               mstate.gworker = caller;
               return;
               break;
            default:
               throw "Invalid state in _MDByteArray";
         }
         this.i4 = cmodule.ccode.__2E_str5104;
         this.i5 = this.i2 + this.i0;
         this.i5 = li8(this.i5);
         mstate.esp -= 12;
         si32(this.i3,mstate.esp);
         si32(this.i4,mstate.esp + 4);
         si32(this.i5,mstate.esp + 8);
         state = 4;
         mstate.esp -= 4;
         FSM_sprintf.start();
      }
   }
}

