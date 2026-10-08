package cmodule.ccode
{
   import avm2.intrinsics.memory.lf64;
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.li8;
   import avm2.intrinsics.memory.sf64;
   import avm2.intrinsics.memory.si32;
   import avm2.intrinsics.memory.si8;
   
   public final class FSM___gdtoa extends Machine
   {
      
      public static const intRegCount:int = 32;
      
      public static const NumberRegCount:int = 4;
      
      public var i21:int;
      
      public var i30:int;
      
      public var i31:int;
      
      public var f0:Number;
      
      public var f1:Number;
      
      public var f3:Number;
      
      public var f2:Number;
      
      public var i10:int;
      
      public var i11:int;
      
      public var i12:int;
      
      public var i13:int;
      
      public var i14:int;
      
      public var i15:int;
      
      public var i17:int;
      
      public var i19:int;
      
      public var i16:int;
      
      public var i18:int;
      
      public var i0:int;
      
      public var i1:int;
      
      public var i22:int;
      
      public var i3:int;
      
      public var i4:int;
      
      public var i5:int;
      
      public var i6:int;
      
      public var i7:int;
      
      public var i8:int;
      
      public var i2:int;
      
      public var i23:int;
      
      public var i24:int;
      
      public var i25:int;
      
      public var i26:int;
      
      public var i27:int;
      
      public var i20:int;
      
      public var i9:int;
      
      public var i28:int;
      
      public var i29:int;
      
      public function FSM___gdtoa()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:FSM___gdtoa = null;
         _loc1_ = new FSM___gdtoa();
         cmodule.ccode.gstate.gworker = _loc1_;
      }
      
      final override public function work() : void
      {
         loop24:
         switch(state)
         {
            case 0:
               mstate.esp -= 4;
               si32(mstate.ebp,mstate.esp);
               mstate.ebp = mstate.esp;
               mstate.esp -= 208;
               this.i0 = li32(mstate.ebp + 16);
               this.i1 = li32(this.i0);
               this.i2 = this.i1 & -49;
               this.i3 = li32(mstate.ebp + 8);
               this.i4 = li32(mstate.ebp + 12);
               si32(this.i2,this.i0);
               this.i1 &= 7;
               this.i2 = li32(mstate.ebp + 20);
               this.i5 = li32(mstate.ebp + 24);
               this.i6 = li32(mstate.ebp + 28);
               this.i7 = li32(mstate.ebp + 32);
               this.i8 = this.i4;
               while(true)
               {
                  if(this.i1 > 2)
                  {
                     if(this.i1 != 3)
                     {
                        if(this.i1 != 4)
                        {
                           addr5344:
                           this.i0 = 0;
                           break;
                        }
                        addr0551:
                        this.i0 = -32768;
                        si32(this.i0,this.i6);
                        this.i0 = li32(cmodule.ccode._freelist);
                        if(this.i0 != 0)
                        {
                           this.i1 = li32(this.i0);
                           si32(this.i1,cmodule.ccode._freelist);
                        }
                        else
                        {
                           this.i0 = cmodule.ccode._private_mem;
                           this.i1 = li32(cmodule.ccode._pmem_next);
                           this.i0 = this.i1 - this.i0;
                           this.i0 >>= 3;
                           this.i0 += 3;
                           if(uint(this.i0) > uint(288))
                           {
                              this.i0 = 24;
                              mstate.esp -= 4;
                              si32(this.i0,mstate.esp);
                              state = 2;
                              mstate.esp -= 4;
                              FSM_malloc.start();
                              return;
                           }
                           this.i0 = 0;
                           this.i2 = this.i1 + 24;
                           si32(this.i2,cmodule.ccode._pmem_next);
                           si32(this.i0,this.i1 + 4);
                           this.i0 = 1;
                           si32(this.i0,this.i1 + 8);
                           this.i0 = this.i1;
                        }
                        this.i1 = 0;
                        si32(this.i1,this.i0 + 16);
                        si32(this.i1,this.i0 + 12);
                        si32(this.i1,this.i0);
                        this.i2 = 78;
                        si8(this.i2,this.i0 + 4);
                        this.i0 += 4;
                        this.i2 = cmodule.ccode.__2E_str262;
                        this.i3 = this.i0;
                        do
                        {
                           this.i4 = this.i2 + this.i1;
                           this.i4 = li8(this.i4 + 1);
                           this.i5 = this.i0 + this.i1;
                           si8(this.i4,this.i5 + 1);
                           this.i1 += 1;
                        }
                        while(this.i4 != 0);
                        if(this.i7 != 0)
                        {
                           addr0412:
                           this.i0 += this.i1;
                           si32(this.i0,this.i7);
                        }
                     }
                     else
                     {
                        this.i0 = -32768;
                        si32(this.i0,this.i6);
                        this.i0 = li32(cmodule.ccode._freelist);
                        if(this.i0 != 0)
                        {
                           this.i1 = li32(this.i0);
                           si32(this.i1,cmodule.ccode._freelist);
                        }
                        else
                        {
                           this.i0 = cmodule.ccode._private_mem;
                           this.i1 = li32(cmodule.ccode._pmem_next);
                           this.i0 = this.i1 - this.i0;
                           this.i0 >>= 3;
                           this.i0 += 3;
                           if(uint(this.i0) > uint(288))
                           {
                              this.i0 = 24;
                              mstate.esp -= 4;
                              si32(this.i0,mstate.esp);
                              state = 1;
                              mstate.esp -= 4;
                              FSM_malloc.start();
                              return;
                           }
                           this.i0 = 0;
                           this.i2 = this.i1 + 24;
                           si32(this.i2,cmodule.ccode._pmem_next);
                           si32(this.i0,this.i1 + 4);
                           this.i0 = 1;
                           si32(this.i0,this.i1 + 8);
                           this.i0 = this.i1;
                        }
                        addr035d:
                        this.i1 = 0;
                        si32(this.i1,this.i0 + 16);
                        si32(this.i1,this.i0 + 12);
                        si32(this.i1,this.i0);
                        this.i2 = 73;
                        si8(this.i2,this.i0 + 4);
                        this.i0 += 4;
                        this.i2 = cmodule.ccode.__2E_str161;
                        this.i3 = this.i0;
                        do
                        {
                           this.i4 = this.i2 + this.i1;
                           this.i4 = li8(this.i4 + 1);
                           this.i5 = this.i0 + this.i1;
                           si8(this.i4,this.i5 + 1);
                           this.i1 += 1;
                        }
                        while(this.i4 != 0);
                        if(this.i7 != 0)
                        {
                           §§goto(addr0412);
                        }
                     }
                     mstate.eax = this.i3;
                     break loop24;
                  }
                  if(this.i1 == 0)
                  {
                     this.i0 = 1;
                     si32(this.i0,this.i6);
                     this.i0 = li32(cmodule.ccode._freelist);
                     if(this.i0 != 0)
                     {
                        this.i1 = li32(this.i0);
                        si32(this.i1,cmodule.ccode._freelist);
                     }
                     else
                     {
                        this.i0 = cmodule.ccode._private_mem;
                        this.i1 = li32(cmodule.ccode._pmem_next);
                        this.i0 = this.i1 - this.i0;
                        this.i0 >>= 3;
                        this.i0 += 3;
                        if(uint(this.i0) > uint(288))
                        {
                           this.i0 = 24;
                           mstate.esp -= 4;
                           si32(this.i0,mstate.esp);
                           state = 7;
                           mstate.esp -= 4;
                           FSM_malloc.start();
                           return;
                        }
                        this.i0 = 0;
                        this.i2 = this.i1 + 24;
                        si32(this.i2,cmodule.ccode._pmem_next);
                        si32(this.i0,this.i1 + 4);
                        this.i0 = 1;
                        si32(this.i0,this.i1 + 8);
                        this.i0 = this.i1;
                     }
                     addr106e:
                     this.i1 = 0;
                     si32(this.i1,this.i0 + 16);
                     si32(this.i1,this.i0 + 12);
                     si32(this.i1,this.i0);
                     this.i2 = 48;
                     si8(this.i2,this.i0 + 4);
                     si8(this.i1,this.i0 + 5);
                     this.i1 = this.i0 + 5;
                     this.i0 += 4;
                     if(this.i7 != 0)
                     {
                        addr0efe:
                        si32(this.i1,this.i7);
                     }
                     break;
                  }
                  this.i1 += -1;
                  if(uint(this.i1) < uint(2))
                  {
                     this.i1 = 32;
                     this.i9 = 0;
                     do
                     {
                        this.i9 += 1;
                        this.i1 <<= 1;
                     }
                     while(this.i1 <= 63);
                     this.i1 = 0;
                     mstate.esp -= 4;
                     si32(this.i9,mstate.esp);
                     state = 3;
                     mstate.esp -= 4;
                     FSM___Balloc_D2A.start();
                     return;
                  }
                  §§goto(addr5344);
               }
               addr0f1d:
               mstate.eax = this.i0;
               break;
            case 1:
               this.i0 = mstate.eax;
               mstate.esp += 4;
               this.i1 = 0;
               si32(this.i1,this.i0 + 4);
               this.i1 = 1;
               si32(this.i1,this.i0 + 8);
               §§goto(addr035d);
            case 2:
               this.i0 = mstate.eax;
               mstate.esp += 4;
               this.i1 = 0;
               si32(this.i1,this.i0 + 4);
               this.i1 = 1;
               si32(this.i1,this.i0 + 8);
               §§goto(addr0551);
            case 3:
               this.i9 = mstate.eax;
               mstate.esp += 4;
               this.i10 = this.i9 + 20;
               this.i11 = this.i9;
               this.i12 = this.i1;
               do
               {
                  this.i13 = this.i8 + this.i12;
                  this.i13 = li32(this.i13);
                  this.i14 = this.i9 + this.i12;
                  si32(this.i13,this.i14 + 20);
                  this.i12 += 4;
                  this.i1 += 1;
               }
               while(this.i1 <= 1);
               this.i1 <<= 2;
               this.i8 = this.i11 + 20;
               this.i1 = this.i8 + this.i1;
               this.i1 -= this.i10;
               this.i1 >>= 2;
               this.i12 = this.i1 + -1;
               this.i13 = this.i12 << 2;
               this.i8 += this.i13;
               this.i8 = li32(this.i8);
               loop26:
               while(true)
               {
                  while(true)
                  {
                     if(this.i8 == 0)
                     {
                        this.i8 = this.i1 << 2;
                        this.i8 = this.i9 + this.i8;
                        this.i8 += 12;
                        while(true)
                        {
                           this.i12 = this.i8;
                           if(this.i1 == 1)
                           {
                              break;
                           }
                           this.i12 = li32(this.i12);
                           this.i8 += -4;
                           this.i1 += -1;
                           if(this.i12 == 0)
                           {
                              continue;
                           }
                           this.i8 = this.i1 + -1;
                        }
                        this.i1 = 0;
                        si32(this.i1,this.i11 + 16);
                        mstate.esp -= 4;
                        si32(this.i11,mstate.esp);
                        mstate.esp -= 4;
                        FSM___trailz_D2A.start();
                        addr07be:
                        this.i1 = mstate.eax;
                        mstate.esp += 4;
                        if(this.i1 != 0)
                        {
                           this.i8 = 0;
                           this.i12 = this.i1;
                           break;
                        }
                        this.i1 = 0;
                        this.i8 = this.i3;
                        break loop26;
                     }
                     this.i8 = this.i12;
                     this.i12 = this.i8 << 2;
                     si32(this.i1,this.i11 + 16);
                     this.i1 = this.i11 + this.i12;
                     this.i1 = li32(this.i1 + 20);
                     this.i12 = uint(this.i1) < uint(65536) ? 16 : 0;
                     this.i1 <<= this.i12;
                     this.i13 = uint(this.i1) < uint(16777216) ? 8 : 0;
                     this.i1 <<= this.i13;
                     this.i14 = uint(this.i1) < uint(268435456) ? 4 : 0;
                     this.i12 = this.i13 | this.i12;
                     this.i1 <<= this.i14;
                     this.i13 = uint(this.i1) < uint(1073741824) ? 2 : 0;
                     this.i12 |= this.i14;
                     this.i12 |= this.i13;
                     this.i1 <<= this.i13;
                     if(this.i1 <= -1)
                     {
                        this.i1 = this.i12;
                     }
                     else
                     {
                        this.i1 &= 1073741824;
                        this.i12 += 1;
                        this.i1 = this.i1 == 0 ? 32 : this.i12;
                     }
                     mstate.esp -= 4;
                     si32(this.i11,mstate.esp);
                     this.i8 <<= 5;
                     mstate.esp -= 4;
                     FSM___trailz_D2A.start();
                  }
                  addr0a12:
                  this.i13 = li32(this.i11 + 16);
                  this.i14 = this.i11 + 16;
                  this.i15 = this.i1 >> 5;
                  this.i16 = this.i11 + 20;
                  if(this.i13 <= this.i15)
                  {
                     addr0a50:
                     this.i1 = this.i16;
                  }
                  else
                  {
                     this.i1 &= 31;
                     if(this.i1 == 0)
                     {
                        if(this.i15 < this.i13)
                        {
                           this.i1 = 0;
                           this.i17 = this.i15 << 2;
                           this.i9 += 20;
                           do
                           {
                              this.i18 = this.i17 + this.i9;
                              this.i18 = li32(this.i18);
                              si32(this.i18,this.i9);
                              this.i9 += 4;
                              this.i1 += 1;
                              this.i18 = this.i15 + this.i1;
                           }
                           while(this.i18 < this.i13);
                           this.i1 <<= 2;
                           this.i1 = this.i11 + this.i1;
                           this.i1 += 20;
                        }
                        else
                        {
                           §§goto(addr0a50);
                        }
                     }
                     else
                     {
                        this.i17 = this.i15 << 2;
                        this.i17 = this.i11 + this.i17;
                        this.i17 = li32(this.i17 + 20);
                        this.i17 >>>= this.i1;
                        this.i18 = 32 - this.i1;
                        this.i19 = this.i15 + 1;
                        if(this.i19 >= this.i13)
                        {
                           this.i1 = this.i16;
                           this.i9 = this.i17;
                        }
                        else
                        {
                           this.i19 = 0;
                           this.i20 = this.i15 << 2;
                           this.i15 += 1;
                           do
                           {
                              this.i21 = this.i20 + this.i9;
                              this.i22 = li32(this.i21 + 24);
                              this.i22 <<= this.i18;
                              this.i17 = this.i22 | this.i17;
                              si32(this.i17,this.i9 + 20);
                              this.i17 = li32(this.i21 + 24);
                              this.i9 += 4;
                              this.i19 += 1;
                              this.i17 >>>= this.i1;
                              this.i21 = this.i15 + this.i19;
                           }
                           while(this.i21 < this.i13);
                           this.i1 = this.i19 << 2;
                           this.i1 = this.i11 + this.i1;
                           this.i1 += 20;
                           this.i9 = this.i17;
                        }
                        si32(this.i9,this.i1);
                        if(this.i9 != 0)
                        {
                           this.i1 += 4;
                        }
                     }
                  }
                  this.i1 -= this.i10;
                  this.i9 = this.i1 >> 2;
                  si32(this.i9,this.i14);
                  if(uint(this.i1) <= uint(3))
                  {
                     this.i1 = 0;
                     si32(this.i1,this.i16);
                  }
                  this.i1 = this.i8 - this.i12;
                  this.i8 = this.i12 + this.i3;
                  break;
               }
               this.i9 = li32(this.i11 + 16);
               if(this.i9 != 0)
               {
                  this.i10 = this.i9 + -1;
                  this.i12 = this.i10 << 2;
                  this.i13 = this.i11 + 20;
                  this.i12 = this.i13 + this.i12;
                  this.i14 = li32(this.i12);
                  this.i15 = uint(this.i14) < uint(65536) ? 16 : 0;
                  this.i16 = this.i14 << this.i15;
                  this.i17 = uint(this.i16) < uint(16777216) ? 8 : 0;
                  this.i16 <<= this.i17;
                  this.i18 = uint(this.i16) < uint(268435456) ? 4 : 0;
                  this.i15 = this.i17 | this.i15;
                  this.i16 <<= this.i18;
                  this.i17 = uint(this.i16) < uint(1073741824) ? 2 : 0;
                  this.i15 |= this.i18;
                  this.i15 |= this.i17;
                  this.i16 <<= this.i17;
                  if(this.i16 > -1)
                  {
                     this.i16 &= 1073741824;
                     this.i15 += 1;
                     this.i15 = this.i16 == 0 ? 32 : this.i15;
                  }
                  if(this.i15 <= 10)
                  {
                     this.i12 = this.i15 + 21;
                     this.i13 = 11 - this.i15;
                     this.i12 = this.i14 << this.i12;
                     this.i14 >>>= this.i13;
                     if(this.i10 <= 0)
                     {
                        this.i13 = this.i14;
                     }
                     else
                     {
                        this.i9 <<= 2;
                        this.i9 += this.i11;
                        this.i9 = li32(this.i9 + 12);
                        this.i13 = this.i9 >>> this.i13;
                        this.i12 = this.i13 | this.i12;
                        this.i13 = this.i14;
                     }
                  }
                  else
                  {
                     if(this.i10 <= 0)
                     {
                        this.i9 = 0;
                     }
                     else
                     {
                        this.i12 = this.i9 << 2;
                        this.i12 += this.i11;
                        this.i9 = li32(this.i12 + 12);
                        this.i12 += 12;
                     }
                     this.i10 = this.i15 + -11;
                     if(this.i15 == 11)
                     {
                        this.i13 = this.i14;
                        this.i12 = this.i9;
                     }
                     else
                     {
                        this.i15 = 43 - this.i15;
                        this.i16 = this.i9 >>> this.i15;
                        this.i14 <<= this.i10;
                        this.i14 = this.i16 | this.i14;
                        if(uint(this.i12) <= uint(this.i13))
                        {
                           this.i12 = 0;
                        }
                        else
                        {
                           this.i12 = li32(this.i12 + -4);
                        }
                        this.i12 >>>= this.i15;
                        this.i13 = this.i9 << this.i10;
                        this.i12 |= this.i13;
                        this.i13 = this.i14;
                     }
                  }
                  this.i9 = this.i13;
                  this.i10 = this.i12;
                  this.i9 |= 1072693248;
                  this.i9 &= 1073741823;
                  si32(this.i10,mstate.ebp + -8);
                  si32(this.i9,mstate.ebp + -4);
                  this.i12 = this.i1 + this.i8;
                  this.i12 += -1;
                  this.f0 = lf64(mstate.ebp + -8);
                  this.f0 += -1.5;
                  this.i13 = this.i12 >> 31;
                  this.i14 = this.i12 + this.i13;
                  this.f1 = Number(this.i12);
                  this.f0 *= 0.28953;
                  this.i13 = this.i14 ^ this.i13;
                  this.f1 *= 0.30103;
                  this.f0 += 0.176091;
                  this.i13 += -1077;
                  this.f0 += this.f1;
                  if(this.i13 > 0)
                  {
                     this.f1 = Number(this.i13);
                     this.f1 *= 7e-17;
                     this.f0 = this.f1 + this.f0;
                  }
                  this.f1 = 0;
                  this.i13 = int(this.f0);
                  while(true)
                  {
                     if(this.f0 < this.f1)
                     {
                        this.f1 = Number(this.i13);
                        if(this.f1 != this.f0)
                        {
                           this.i13 += -1;
                           break;
                        }
                     }
                     break;
                  }
                  this.i14 = this.i8 + this.i1;
                  this.i14 <<= 20;
                  this.i9 = this.i14 + this.i9;
                  this.i9 += -1048576;
                  if(uint(this.i13) >= uint(23))
                  {
                     this.i14 = 1;
                  }
                  else
                  {
                     this.i14 = cmodule.ccode.___tens_D2A;
                     this.i15 = this.i13 << 3;
                     si32(this.i10,mstate.ebp + -16);
                     si32(this.i9,mstate.ebp + -12);
                     this.i14 += this.i15;
                     this.f0 = lf64(mstate.ebp + -16);
                     this.f1 = lf64(this.i14);
                     if(this.f0 >= this.f1)
                     {
                        this.i14 = 0;
                     }
                     else
                     {
                        this.i14 = 0;
                        this.i13 += -1;
                     }
                  }
                  this.i15 = this.i1 - this.i12;
                  this.i16 = this.i15 + -1;
                  this.i15 = 1 - this.i15;
                  this.i17 = this.i16 > -1 ? this.i16 : 0;
                  this.i15 = this.i16 > -1 ? 0 : this.i15;
                  if(this.i13 >= 0)
                  {
                     this.i16 = 0;
                     this.i17 += this.i13;
                     this.i18 = this.i13;
                  }
                  else
                  {
                     this.i16 = 0;
                     this.i19 = 0 - this.i13;
                     this.i15 -= this.i13;
                     this.i18 = this.i16;
                     this.i16 = this.i19;
                  }
                  this.i2 = uint(this.i2) > uint(9) ? 0 : this.i2;
                  this.i19 = this.i2 + -4;
                  this.i19 = this.i2 < 6 ? this.i2 : this.i19;
                  this.i2 = this.i2 < 6 ? 1 : 0;
                  this.i20 = this.i5 < 1 ? 1 : this.i5;
                  if(this.i19 <= 2)
                  {
                     if(uint(this.i19) >= uint(2))
                     {
                        if(this.i19 != 2)
                        {
                           addr172f:
                           this.i21 = 1;
                           this.i22 = this.i20;
                           this.i23 = this.i20;
                        }
                        else
                        {
                           this.i5 = 0;
                           this.i12 = this.i20;
                           this.i21 = this.i5;
                           this.i22 = this.i20;
                           this.i23 = this.i20;
                           this.i5 = this.i20;
                        }
                     }
                     else
                     {
                        this.i5 = 0;
                        this.i20 = -1;
                        this.i21 = 1;
                        this.i12 = 22;
                        this.i22 = this.i20;
                        this.i23 = this.i20;
                     }
                  }
                  else
                  {
                     while(true)
                     {
                        if(this.i19 != 3)
                        {
                           if(this.i19 == 4)
                           {
                              this.i5 = 1;
                              this.i12 = this.i20;
                              this.i21 = this.i5;
                              this.i22 = this.i20;
                              this.i23 = this.i20;
                              this.i5 = this.i20;
                              break;
                           }
                           if(this.i19 == 5)
                           {
                              this.i12 = 1;
                           }
                           else
                           {
                              §§goto(addr172f);
                           }
                        }
                        else
                        {
                           this.i12 = 0;
                        }
                        this.i21 = this.i12;
                        this.i22 = this.i13 + this.i5;
                        this.i23 = this.i22 + 1;
                        if(this.i23 >= 1)
                        {
                           this.i12 = this.i23;
                           break;
                        }
                        this.i12 = 1;
                        break;
                     }
                  }
                  this.i20 = this.i21;
                  this.i21 = this.i22;
                  this.i22 = this.i23;
                  si32(this.i5,mstate.ebp + -207);
                  if(uint(this.i12) >= uint(20))
                  {
                     this.i5 = 4;
                     this.i23 = 0;
                     do
                     {
                        this.i5 <<= 1;
                        this.i23 += 1;
                        this.i24 = this.i5 + 16;
                     }
                     while(uint(this.i24) <= uint(this.i12));
                     this.i5 = this.i23;
                  }
                  else
                  {
                     this.i5 = 0;
                  }
                  mstate.esp -= 4;
                  si32(this.i5,mstate.esp);
                  state = 8;
                  mstate.esp -= 4;
                  FSM___Balloc_D2A.start();
                  return;
               }
               if(this.i11 != 0)
               {
                  this.i0 = cmodule.ccode._freelist;
                  this.i1 = li32(this.i11 + 4);
                  this.i1 <<= 2;
                  this.i0 += this.i1;
                  this.i1 = li32(this.i0);
                  si32(this.i1,this.i11);
                  si32(this.i11,this.i0);
               }
               this.i0 = 1;
               si32(this.i0,this.i6);
               this.i0 = li32(cmodule.ccode._freelist);
               if(this.i0 != 0)
               {
                  this.i1 = li32(this.i0);
                  si32(this.i1,cmodule.ccode._freelist);
               }
               else
               {
                  this.i0 = cmodule.ccode._private_mem;
                  this.i1 = li32(cmodule.ccode._pmem_next);
                  this.i0 = this.i1 - this.i0;
                  this.i0 >>= 3;
                  this.i0 += 3;
                  if(uint(this.i0) > uint(288))
                  {
                     this.i0 = 24;
                     mstate.esp -= 4;
                     si32(this.i0,mstate.esp);
                     state = 6;
                     mstate.esp -= 4;
                     FSM_malloc.start();
                     return;
                  }
                  this.i0 = 0;
                  this.i2 = this.i1 + 24;
                  si32(this.i2,cmodule.ccode._pmem_next);
                  si32(this.i0,this.i1 + 4);
                  this.i0 = 1;
                  si32(this.i0,this.i1 + 8);
                  this.i0 = this.i1;
               }
               addr0e93:
               this.i1 = 0;
               si32(this.i1,this.i0 + 16);
               si32(this.i1,this.i0 + 12);
               si32(this.i1,this.i0);
               this.i2 = 48;
               si8(this.i2,this.i0 + 4);
               si8(this.i1,this.i0 + 5);
               this.i1 = this.i0 + 5;
               this.i0 += 4;
               if(this.i7 != 0)
               {
                  §§goto(addr0efe);
               }
               §§goto(addr0f1d);
            case 5:
               addr09c4:
               this.i13 = mstate.eax;
               this.i1 = this.i8 - this.i1;
               mstate.esp += 4;
               this.i8 = this.i1 + 32;
               if(this.i13 == 0)
               {
                  this.i1 = this.i8;
                  this.i8 = this.i3;
                  break loop26;
               }
               this.i12 = this.i13;
               this.i1 = this.i13;
               §§goto(addr0a12);
               break;
            case 4:
               §§goto(addr07be);
            case 6:
               this.i0 = mstate.eax;
               mstate.esp += 4;
               this.i1 = 0;
               si32(this.i1,this.i0 + 4);
               this.i1 = 1;
               si32(this.i1,this.i0 + 8);
               §§goto(addr0e93);
            case 7:
               this.i0 = mstate.eax;
               mstate.esp += 4;
               this.i1 = 0;
               si32(this.i1,this.i0 + 4);
               this.i1 = 1;
               si32(this.i1,this.i0 + 8);
               §§goto(addr106e);
            case 8:
               this.i12 = mstate.eax;
               mstate.esp += 4;
               si32(this.i5,this.i12);
               this.i5 = this.i12 + 4;
               this.i12 = uint(this.i22) > uint(14) ? 1 : 0;
               this.i2 ^= 1;
               this.i2 = this.i12 | this.i2;
               this.i12 = this.i5;
               this.i2 &= 1;
               while(true)
               {
                  loop31:
                  while(true)
                  {
                     loop32:
                     while(true)
                     {
                        loop33:
                        while(true)
                        {
                           while(true)
                           {
                              if(this.i2 == 0)
                              {
                                 if(this.i13 == 0)
                                 {
                                    loop35:
                                    while(true)
                                    {
                                       if(this.i13 >= 1)
                                       {
                                          this.i2 = cmodule.ccode.___tens_D2A;
                                          this.i23 = this.i13 & 0x0F;
                                          this.i23 <<= 3;
                                          this.i2 += this.i23;
                                          this.f0 = lf64(this.i2);
                                          this.i2 = this.i13 >> 4;
                                          this.i23 = this.i13 & 0x0100;
                                          loop36:
                                          while(true)
                                          {
                                             if(this.i23 == 0)
                                             {
                                                this.i23 = 2;
                                                this.i24 = 0;
                                                this.i25 = this.i10;
                                                this.i26 = this.i9;
                                                while(true)
                                                {
                                                   this.i27 = this.i26;
                                                   this.i28 = this.i23;
                                                   if(this.i2 == 0)
                                                   {
                                                      break loop36;
                                                   }
                                                   this.i26 = this.i24;
                                                   this.i23 = this.i25;
                                                   this.i24 = this.i27;
                                                   this.i25 = this.i28;
                                                }
                                                break;
                                                addr1b5c:
                                             }
                                             else
                                             {
                                                si32(this.i10,mstate.ebp + -24);
                                                si32(this.i9,mstate.ebp + -20);
                                                this.f1 = lf64(mstate.ebp + -24);
                                                this.f1 /= 1e+256;
                                                sf64(this.f1,mstate.ebp + -32);
                                                this.i23 = li32(mstate.ebp + -32);
                                                this.i24 = li32(mstate.ebp + -28);
                                                this.i2 &= 15;
                                                if(this.i2 == 0)
                                                {
                                                   this.i2 = 3;
                                                   addr1d9b:
                                                   break loop35;
                                                }
                                                this.i25 = 3;
                                                this.i26 = 0;
                                             }
                                             this.i27 = this.i24;
                                             this.i24 = this.i25;
                                             this.i25 = this.i2 & 1;
                                             if(this.i25 == 0)
                                             {
                                                addr1b26:
                                                this.i28 = this.i24;
                                                this.i24 = this.i26 + 1;
                                                this.i2 >>= 1;
                                                this.i25 = this.i23;
                                                this.i26 = this.i27;
                                                this.i23 = this.i28;
                                                §§goto(addr1b5c);
                                             }
                                             this.i25 = cmodule.ccode.___bigtens_D2A;
                                             this.i28 = this.i26 << 3;
                                             this.i25 += this.i28;
                                             this.f1 = lf64(this.i25);
                                             this.f0 = this.f1 * this.f0;
                                             this.i24 += 1;
                                             §§goto(addr1b26);
                                          }
                                          this.i23 = this.i25;
                                          this.i24 = this.i27;
                                          this.i2 = this.i28;
                                          break;
                                       }
                                       this.i2 = 0 - this.i13;
                                       if(this.i13 == 0)
                                       {
                                          this.f0 = 1;
                                          this.i2 = 2;
                                          this.i23 = this.i10;
                                          this.i24 = this.i9;
                                          break;
                                       }
                                       this.i23 = cmodule.ccode.___tens_D2A;
                                       this.i24 = this.i2 & 0x0F;
                                       this.i24 <<= 3;
                                       si32(this.i10,mstate.ebp + -40);
                                       si32(this.i9,mstate.ebp + -36);
                                       this.i23 += this.i24;
                                       this.f0 = lf64(this.i23);
                                       this.f1 = lf64(mstate.ebp + -40);
                                       this.f0 = this.f1 * this.f0;
                                       sf64(this.f0,mstate.ebp + -48);
                                       this.i23 = li32(mstate.ebp + -48);
                                       this.i24 = li32(mstate.ebp + -44);
                                       this.i25 = this.i2 >> 4;
                                       if(uint(this.i2) >= uint(16))
                                       {
                                          this.i2 = cmodule.ccode.___bigtens_D2A;
                                          this.i26 = 2;
                                          while(true)
                                          {
                                             this.i27 = this.i2;
                                             this.i28 = this.i25 & 1;
                                             if(this.i28 != 0)
                                             {
                                                si32(this.i23,mstate.ebp + -56);
                                                si32(this.i24,mstate.ebp + -52);
                                                this.f0 = lf64(this.i27);
                                                this.f1 = lf64(mstate.ebp + -56);
                                                this.f0 = this.f1 * this.f0;
                                                sf64(this.f0,mstate.ebp + -64);
                                                this.i23 = li32(mstate.ebp + -64);
                                                this.i24 = li32(mstate.ebp + -60);
                                                this.i26 += 1;
                                             }
                                             this.i2 += 8;
                                             this.i27 = this.i25 >> 1;
                                             if(uint(this.i25) < uint(2))
                                             {
                                                break;
                                             }
                                             this.i25 = this.i27;
                                          }
                                          this.f0 = 1;
                                          this.i2 = this.i26;
                                          break;
                                       }
                                       this.f0 = 1;
                                       this.i2 = 2;
                                       §§goto(addr1d9b);
                                    }
                                    while(true)
                                    {
                                       if(this.i14 != 0)
                                       {
                                          this.f1 = 1;
                                          si32(this.i23,mstate.ebp + -72);
                                          si32(this.i24,mstate.ebp + -68);
                                          this.f2 = lf64(mstate.ebp + -72);
                                          if(this.f2 < this.f1)
                                          {
                                             if(this.i22 >= 1)
                                             {
                                                if(this.i21 >= 1)
                                                {
                                                   this.f1 = this.f2 * 10;
                                                   sf64(this.f1,mstate.ebp + -80);
                                                   this.i23 = li32(mstate.ebp + -80);
                                                   this.i24 = li32(mstate.ebp + -76);
                                                   this.i2 += 1;
                                                   this.i25 = this.i13 + -1;
                                                   this.i26 = this.i21;
                                                   break;
                                                }
                                                §§goto(addr2654);
                                             }
                                          }
                                       }
                                       this.i25 = this.i13;
                                       this.i26 = this.i22;
                                       break;
                                    }
                                    si32(this.i23,mstate.ebp + -88);
                                    si32(this.i24,mstate.ebp + -84);
                                    this.f1 = lf64(mstate.ebp + -88);
                                    this.f2 = Number(this.i2);
                                    this.f2 *= this.f1;
                                    this.f2 += 7;
                                    sf64(this.f2,mstate.ebp + -96);
                                    this.i2 = li32(mstate.ebp + -92);
                                    this.i27 = li32(mstate.ebp + -96);
                                    this.i2 += -54525952;
                                    if(this.i26 == 0)
                                    {
                                       si32(this.i27,mstate.ebp + -104);
                                       si32(this.i2,mstate.ebp + -100);
                                       this.f0 = lf64(mstate.ebp + -104);
                                       this.f1 += -5;
                                       if(this.f1 > this.f0)
                                       {
                                          this.i1 = 0;
                                          this.i2 = this.i11;
                                          this.i3 = this.i25;
                                          this.i4 = this.i1;
                                          break;
                                       }
                                       this.f0 = -this.f0;
                                       if(this.f1 < this.f0)
                                       {
                                          break loop31;
                                       }
                                    }
                                    else
                                    {
                                       if(this.i20 != 0)
                                       {
                                          this.i28 = cmodule.ccode.___tens_D2A;
                                          this.i29 = this.i26 << 3;
                                          si32(this.i27,mstate.ebp + -112);
                                          si32(this.i2,mstate.ebp + -108);
                                          this.i2 = this.i29 + this.i28;
                                          this.f1 = lf64(this.i2 + -8);
                                          this.f2 = this.f0 * 0.5;
                                          this.f3 = lf64(mstate.ebp + -112);
                                          this.f1 = this.f2 / this.f1;
                                          this.i2 = 0;
                                          this.f1 -= this.f3;
                                          while(true)
                                          {
                                             si32(this.i23,mstate.ebp + -120);
                                             si32(this.i24,mstate.ebp + -116);
                                             this.f2 = lf64(mstate.ebp + -120);
                                             this.f3 = this.f2 / this.f0;
                                             this.i23 = int(this.f3);
                                             this.f3 = Number(this.i23);
                                             this.f3 *= this.f0;
                                             this.i23 += 48;
                                             this.i24 = this.i12 + this.i2;
                                             si8(this.i23,this.i24);
                                             this.i23 = this.i2 + 1;
                                             this.f2 -= this.f3;
                                             this.i24 = this.i23;
                                             if(this.f2 < this.f1)
                                             {
                                                this.f1 = 0;
                                                this.i2 = this.i5 + this.i24;
                                                if(this.f2 == this.f1)
                                                {
                                                   this.i1 = 0;
                                                   this.i3 = this.i11;
                                                   this.i23 = this.i25;
                                                   break loop32;
                                                }
                                                if(this.i11 != 0)
                                                {
                                                   this.i1 = cmodule.ccode._freelist;
                                                   this.i3 = li32(this.i11 + 4);
                                                   this.i3 <<= 2;
                                                   this.i1 += this.i3;
                                                   this.i3 = li32(this.i1);
                                                   si32(this.i3,this.i11);
                                                   si32(this.i11,this.i1);
                                                }
                                                this.i1 = 0;
                                                si8(this.i1,this.i2);
                                                this.i1 = this.i25 + 1;
                                                si32(this.i1,this.i6);
                                                if(this.i7 != 0)
                                                {
                                                   this.i1 = 16;
                                                   §§goto(addr5297);
                                                }
                                                else
                                                {
                                                   this.i2 = 16;
                                                   §§goto(addr52d2);
                                                }
                                             }
                                             else
                                             {
                                                this.f3 = this.f0 - this.f2;
                                                if(this.f3 < this.f1)
                                                {
                                                   this.i2 = this.i5 + this.i24;
                                                   this.i1 = this.i25;
                                                   break loop33;
                                                }
                                                if(this.i23 < this.i26)
                                                {
                                                   continue;
                                                }
                                             }
                                             this.f2 *= 10;
                                             sf64(this.f2,mstate.ebp + -128);
                                             this.i23 = li32(mstate.ebp + -128);
                                             this.i24 = li32(mstate.ebp + -124);
                                             this.i2 += 1;
                                             this.f1 *= 10;
                                          }
                                          break loop33;
                                       }
                                       this.i28 = cmodule.ccode.___tens_D2A;
                                       this.i29 = this.i26 << 3;
                                       si32(this.i27,mstate.ebp + -136);
                                       si32(this.i2,mstate.ebp + -132);
                                       this.i2 = this.i29 + this.i28;
                                       this.f1 /= this.f0;
                                       this.f2 = lf64(mstate.ebp + -136);
                                       this.f3 = lf64(this.i2 + -8);
                                       this.i2 = int(this.f1);
                                       this.f1 = this.f2 * this.f3;
                                       if(this.i2 != 0)
                                       {
                                          this.i27 = 1;
                                          this.i28 = this.i5;
                                          while(true)
                                          {
                                             si32(this.i23,mstate.ebp + -144);
                                             si32(this.i24,mstate.ebp + -140);
                                             this.f2 = Number(this.i2);
                                             this.f3 = lf64(mstate.ebp + -144);
                                             this.f2 *= this.f0;
                                             this.f2 = this.f3 - this.f2;
                                             sf64(this.f2,mstate.ebp + -152);
                                             this.i23 = li32(mstate.ebp + -152);
                                             this.i24 = li32(mstate.ebp + -148);
                                             this.i27 += this.i23;
                                             this.i28 += this.i23;
                                             this.i23 = this.i2;
                                             this.i2 = this.i29;
                                          }
                                          §§goto(addr09c4);
                                          addr2334:
                                       }
                                       else
                                       {
                                          this.i27 = 1;
                                          this.i28 = this.i5;
                                       }
                                       this.i29 = 0;
                                       this.i30 = this.i28;
                                       this.i31 = this.i29;
                                       this.i29 = this.i2;
                                       this.i2 = this.i23;
                                       this.i23 = this.i24;
                                       while(true)
                                       {
                                          this.i24 = this.i29;
                                          this.i24 += 48;
                                          this.i29 = this.i30 + this.i31;
                                          si8(this.i24,this.i29);
                                          this.i24 = this.i31 + 1;
                                          this.i29 = this.i27 + this.i31;
                                          if(this.i29 == this.i26)
                                          {
                                             break;
                                          }
                                          si32(this.i2,mstate.ebp + -168);
                                          si32(this.i23,mstate.ebp + -164);
                                          this.f2 = lf64(mstate.ebp + -168);
                                          this.f2 *= 10;
                                          sf64(this.f2,mstate.ebp + -176);
                                          this.f2 /= this.f0;
                                          this.i2 = li32(mstate.ebp + -176);
                                          this.i24 = li32(mstate.ebp + -172);
                                          this.i23 = this.i31 + 1;
                                          this.i29 = int(this.f2);
                                          if(this.i29 == 0)
                                          {
                                             continue;
                                          }
                                          this.i27 += this.i23;
                                          this.i28 += this.i23;
                                          this.i23 = this.i2;
                                          this.i2 = this.i29;
                                          §§goto(addr2334);
                                          this.i31 = this.i23;
                                          this.i23 = this.i24;
                                       }
                                       si32(this.i2,mstate.ebp + -160);
                                       si32(this.i23,mstate.ebp + -156);
                                       this.f2 = lf64(mstate.ebp + -160);
                                       this.f0 *= 0.5;
                                       this.i2 = this.i28 + this.i24;
                                       this.f3 = this.f1 + this.f0;
                                       if(this.f2 > this.f3)
                                       {
                                          this.i1 = this.i25;
                                          break loop33;
                                       }
                                       this.f0 -= this.f1;
                                       if(this.f2 < this.f0)
                                       {
                                          this.i2 = 0;
                                          do
                                          {
                                             this.i1 = this.i2 ^ -1;
                                             this.i1 = this.i24 + this.i1;
                                             this.i1 = this.i28 + this.i1;
                                             this.i1 = li8(this.i1);
                                             this.i2 += 1;
                                          }
                                          while(this.i1 == 48);
                                          this.f0 = 0;
                                          this.i2 += -1;
                                          this.i2 = this.i24 - this.i2;
                                          this.i2 = this.i28 + this.i2;
                                          if(this.f2 == this.f0)
                                          {
                                             this.i1 = 0;
                                             this.i3 = this.i11;
                                             this.i23 = this.i25;
                                             break loop32;
                                          }
                                          this.i1 = 16;
                                          this.i3 = this.i11;
                                          this.i23 = this.i25;
                                          break loop32;
                                       }
                                    }
                                 }
                              }
                              addr2654:
                              if(this.i13 <= 14)
                              {
                                 if(this.i8 >= 0)
                                 {
                                    this.i1 = cmodule.ccode.___tens_D2A;
                                    this.i2 = this.i13 << 3;
                                    this.i1 += this.i2;
                                    this.f0 = lf64(this.i1);
                                    this.i1 = li32(mstate.ebp + -207);
                                    if(this.i1 <= -1)
                                    {
                                       if(this.i22 < 1)
                                       {
                                          if(this.i22 >= 0)
                                          {
                                             si32(this.i10,mstate.ebp + -184);
                                             si32(this.i9,mstate.ebp + -180);
                                             this.f1 = lf64(mstate.ebp + -184);
                                             this.f0 *= 5;
                                             if(this.f1 > this.f0)
                                             {
                                                this.i1 = 0;
                                                this.i2 = this.i11;
                                                this.i3 = this.i13;
                                                this.i4 = this.i1;
                                                addr1f5f:
                                                break;
                                             }
                                          }
                                          break loop31;
                                       }
                                    }
                                    this.i1 = 0;
                                    this.i2 = this.i10;
                                    this.i3 = this.i9;
                                    while(true)
                                    {
                                       this.f1 = 0;
                                       si32(this.i2,mstate.ebp + -192);
                                       si32(this.i3,mstate.ebp + -188);
                                       this.f2 = lf64(mstate.ebp + -192);
                                       this.f3 = this.f2 / this.f0;
                                       this.i2 = int(this.f3);
                                       this.f3 = Number(this.i2);
                                       this.f3 *= this.f0;
                                       this.i3 = this.i2 + 48;
                                       this.i4 = this.i12 + this.i1;
                                       si8(this.i3,this.i4);
                                       this.i3 = this.i1 + 1;
                                       this.f2 -= this.f3;
                                       this.i4 = this.i3;
                                       if(this.f2 == this.f1)
                                       {
                                          this.i2 = 0;
                                          this.i4 = this.i5 + this.i4;
                                          this.i3 = this.i11;
                                          this.i23 = this.i13;
                                          this.i1 = this.i2;
                                          this.i2 = this.i4;
                                          break loop32;
                                       }
                                       if(this.i3 != this.i22)
                                       {
                                          continue;
                                       }
                                       this.f2 += this.f2;
                                       this.i4 = this.i5 + this.i4;
                                       if(this.f2 <= this.f0)
                                       {
                                          if(this.f2 == this.f0)
                                          {
                                             this.i1 = this.i2 & 1;
                                             if(this.i1 != 0)
                                             {
                                                addr27dd:
                                                this.i1 = this.i13;
                                                this.i2 = this.i4;
                                                break loop33;
                                             }
                                          }
                                          this.i1 = 16;
                                          this.i3 = this.i11;
                                          this.i23 = this.i13;
                                          this.i2 = this.i4;
                                          break loop32;
                                       }
                                       §§goto(addr27dd);
                                       this.f1 = this.f2 * 10;
                                       sf64(this.f1,mstate.ebp + -200);
                                       this.i2 = li32(mstate.ebp + -200);
                                       this.i3 = li32(mstate.ebp + -196);
                                       this.i1 += 1;
                                    }
                                    break loop32;
                                 }
                              }
                              loop38:
                              while(true)
                              {
                                 while(true)
                                 {
                                    if(this.i20 == 0)
                                    {
                                       this.i2 = 0;
                                       this.i8 = this.i18;
                                       this.i18 = this.i16;
                                       this.i23 = this.i15;
                                    }
                                    else
                                    {
                                       if(this.i19 <= 1)
                                       {
                                          this.i2 = 65 - this.i1;
                                          this.i23 = 64 - this.i1;
                                          this.i23 = this.i8 - this.i23;
                                          if(this.i23 < -16445)
                                          {
                                             this.i2 = this.i8 + 16446;
                                             this.i23 = li32(cmodule.ccode._freelist + 4);
                                             this.i8 = this.i2 + this.i17;
                                             this.i2 += this.i15;
                                             if(this.i23 != 0)
                                             {
                                                this.i17 = li32(this.i23);
                                                si32(this.i17,cmodule.ccode._freelist + 4);
                                             }
                                             else
                                             {
                                                this.i23 = cmodule.ccode._private_mem;
                                                this.i17 = li32(cmodule.ccode._pmem_next);
                                                this.i23 = this.i17 - this.i23;
                                                this.i23 >>= 3;
                                                this.i23 += 4;
                                                if(uint(this.i23) > uint(288))
                                                {
                                                   this.i23 = 32;
                                                   mstate.esp -= 4;
                                                   si32(this.i23,mstate.esp);
                                                   state = 9;
                                                   mstate.esp -= 4;
                                                   FSM_malloc.start();
                                                   return;
                                                }
                                                this.i23 = 1;
                                                this.i9 = this.i17 + 32;
                                                si32(this.i9,cmodule.ccode._pmem_next);
                                                si32(this.i23,this.i17 + 4);
                                                this.i23 = 2;
                                                si32(this.i23,this.i17 + 8);
                                                this.i23 = this.i17;
                                             }
                                             addr2c26:
                                             this.i17 = 0;
                                             si32(this.i17,this.i23 + 12);
                                             this.i17 = 1;
                                             si32(this.i17,this.i23 + 20);
                                             si32(this.i17,this.i23 + 16);
                                             if(this.i8 >= 1)
                                             {
                                                if(this.i15 > 0)
                                                {
                                                   this.i17 = this.i16;
                                                   break;
                                                }
                                             }
                                             this.i17 = this.i16;
                                             break loop38;
                                          }
                                          this.i8 = this.i18;
                                          this.i18 = this.i16;
                                          this.i23 = this.i15;
                                       }
                                       else
                                       {
                                          this.i9 = this.i22 + -1;
                                          while(true)
                                          {
                                             if(this.i16 >= this.i9)
                                             {
                                                this.i23 = this.i16 - this.i9;
                                                if(this.i22 >= 0)
                                                {
                                                   this.i2 = this.i22;
                                                   this.i8 = this.i18;
                                                   this.i18 = this.i23;
                                                   this.i23 = this.i15;
                                                   break;
                                                }
                                                this.i2 = this.i18;
                                                this.i18 = this.i23;
                                             }
                                             else
                                             {
                                                this.i2 = this.i9 - this.i16;
                                                this.i16 = this.i2 + this.i18;
                                                if(this.i22 >= 0)
                                                {
                                                   this.i18 = 0;
                                                   this.i2 = this.i22;
                                                   this.i8 = this.i16;
                                                   this.i23 = this.i15;
                                                   this.i16 = this.i9;
                                                   break;
                                                }
                                                this.i18 = 0;
                                                this.i2 = this.i16;
                                                this.i16 = this.i9;
                                             }
                                             this.i23 = this.i2;
                                             this.i2 = 0;
                                             this.i9 = this.i15 - this.i22;
                                             this.i8 = this.i23;
                                             this.i23 = this.i9;
                                             break;
                                          }
                                       }
                                       this.i9 = li32(cmodule.ccode._freelist + 4);
                                       this.i17 = this.i2 + this.i17;
                                       this.i15 = this.i2 + this.i15;
                                       if(this.i9 != 0)
                                       {
                                          this.i2 = li32(this.i9);
                                          si32(this.i2,cmodule.ccode._freelist + 4);
                                          this.i2 = this.i9;
                                       }
                                       else
                                       {
                                          this.i2 = cmodule.ccode._private_mem;
                                          this.i9 = li32(cmodule.ccode._pmem_next);
                                          this.i2 = this.i9 - this.i2;
                                          this.i2 >>= 3;
                                          this.i2 += 4;
                                          if(uint(this.i2) > uint(288))
                                          {
                                             this.i2 = 32;
                                             mstate.esp -= 4;
                                             si32(this.i2,mstate.esp);
                                             state = 10;
                                             mstate.esp -= 4;
                                             FSM_malloc.start();
                                             return;
                                          }
                                          this.i2 = 1;
                                          this.i10 = this.i9 + 32;
                                          si32(this.i10,cmodule.ccode._pmem_next);
                                          si32(this.i2,this.i9 + 4);
                                          this.i2 = 2;
                                          si32(this.i2,this.i9 + 8);
                                          this.i2 = this.i9;
                                       }
                                       addr2eca:
                                       this.i9 = 0;
                                       si32(this.i9,this.i2 + 12);
                                       this.i9 = 1;
                                       si32(this.i9,this.i2 + 20);
                                       si32(this.i9,this.i2 + 16);
                                    }
                                    this.i9 = this.i17;
                                    this.i17 = this.i18;
                                    this.i10 = this.i23;
                                    this.i24 = this.i15;
                                    if(this.i10 >= 1)
                                    {
                                       if(this.i9 > 0)
                                       {
                                          this.i18 = this.i8;
                                          this.i8 = this.i9;
                                          this.i15 = this.i10;
                                          this.i23 = this.i2;
                                          this.i2 = this.i24;
                                          break;
                                       }
                                    }
                                    this.i18 = this.i8;
                                    this.i23 = this.i2;
                                    this.i8 = this.i9;
                                    this.i15 = this.i10;
                                    this.i2 = this.i24;
                                    break loop38;
                                 }
                                 this.i9 = this.i8 <= this.i15 ? this.i8 : this.i15;
                                 this.i8 -= this.i9;
                                 this.i15 -= this.i9;
                                 this.i2 -= this.i9;
                                 break;
                              }
                              this.i9 = this.i18;
                              this.i10 = this.i17;
                              if(this.i16 <= 0)
                              {
                                 this.i10 = this.i11;
                              }
                              else
                              {
                                 if(this.i20 == 0)
                                 {
                                    mstate.esp -= 8;
                                    si32(this.i11,mstate.esp);
                                    si32(this.i16,mstate.esp + 4);
                                    state = 15;
                                    mstate.esp -= 4;
                                    FSM___pow5mult_D2A.start();
                                    return;
                                 }
                                 if(this.i10 > 0)
                                 {
                                    mstate.esp -= 8;
                                    si32(this.i23,mstate.esp);
                                    si32(this.i10,mstate.esp + 4);
                                    state = 11;
                                    mstate.esp -= 4;
                                    FSM___pow5mult_D2A.start();
                                    return;
                                 }
                                 if(this.i16 != this.i10)
                                 {
                                    mstate.esp -= 8;
                                    this.i10 = this.i16 - this.i10;
                                    si32(this.i11,mstate.esp);
                                    si32(this.i10,mstate.esp + 4);
                                    state = 13;
                                    mstate.esp -= 4;
                                    FSM___pow5mult_D2A.start();
                                    return;
                                 }
                                 this.i10 = this.i11;
                              }
                              §§goto(addr3378);
                           }
                           this.i11 = 49;
                           si8(this.i11,this.i5);
                           this.i11 = 32;
                           this.i13 = 0;
                           this.i3 += 1;
                           this.i23 = this.i5 + 1;
                           this.i8 = this.i11;
                           this.i11 = this.i23;
                           addr5019:
                           this.i23 = this.i3;
                           this.i3 = this.i4;
                           this.i9 = this.i11;
                           if(this.i1 != 0)
                           {
                              this.i4 = cmodule.ccode._freelist;
                              this.i11 = li32(this.i1 + 4);
                              this.i11 <<= 2;
                              this.i4 += this.i11;
                              this.i11 = li32(this.i4);
                              si32(this.i11,this.i1);
                              si32(this.i1,this.i4);
                           }
                           if(this.i3 == 0)
                           {
                              this.i3 = this.i2;
                              this.i1 = this.i8;
                              this.i2 = this.i9;
                              break loop32;
                           }
                           this.i11 = this.i13;
                           this.i4 = this.i23;
                           this.i1 = this.i8;
                           this.i13 = this.i9;
                           §§goto(addr50b1);
                        }
                        this.i3 = li8(this.i2 + -1);
                        this.i4 = this.i2 + -1;
                        this.i8 = this.i2;
                        if(this.i3 != 57)
                        {
                           this.i3 = this.i4;
                        }
                        else
                        {
                           this.i3 = 0;
                           this.i4 = this.i8;
                           this.i8 = this.i2;
                           while(true)
                           {
                              this.i12 = this.i3 ^ -1;
                              this.i12 = this.i2 + this.i12;
                              if(this.i12 == this.i5)
                              {
                                 break;
                              }
                              this.i8 = li8(this.i4 + -2);
                              this.i4 += -1;
                              this.i3 += 1;
                              if(this.i8 == 57)
                              {
                                 continue;
                              }
                              this.i3 = this.i4 + -1;
                              this.i2 = this.i12;
                              this.i8 = this.i12;
                           }
                           this.i2 = 48;
                           si8(this.i2,this.i12);
                           this.i1 += 1;
                           this.i2 = this.i8;
                           this.i3 = this.i12;
                        }
                        this.i4 = 32;
                        this.i8 = li8(this.i3);
                        this.i8 += 1;
                        si8(this.i8,this.i3);
                        this.i3 = this.i11;
                        this.i23 = this.i1;
                        this.i1 = this.i4;
                        break;
                     }
                     §§goto(addr5210);
                  }
                  this.i1 = 0;
                  this.i2 = this.i11;
                  this.i3 = this.i1;
                  break;
               }
               this.i4 = li32(mstate.ebp + -207);
               this.i4 ^= -1;
               if(this.i1 != 0)
               {
                  this.i11 = cmodule.ccode._freelist;
                  this.i13 = li32(this.i1 + 4);
                  this.i13 <<= 2;
                  this.i11 += this.i13;
                  this.i13 = li32(this.i11);
                  si32(this.i13,this.i1);
                  si32(this.i1,this.i11);
               }
               if(this.i3 != 0)
               {
                  this.i1 = 16;
                  this.i11 = 0;
                  this.i13 = this.i5;
                  this.i23 = this.i11 == this.i3 ? 1 : 0;
                  this.i8 = this.i11 == 0 ? 1 : 0;
                  this.i23 |= this.i8;
                  addr50b1:
                  if(this.i11 != 0)
                  {
                     this.i23 &= 1;
                     if(this.i23 == 0)
                     {
                        this.i23 = cmodule.ccode._freelist;
                        this.i8 = li32(this.i11 + 4);
                        this.i8 <<= 2;
                        this.i23 += this.i8;
                        this.i8 = li32(this.i23);
                        si32(this.i8,this.i11);
                        si32(this.i11,this.i23);
                     }
                  }
                  if(this.i3 == 0)
                  {
                     this.i3 = this.i2;
                     this.i23 = this.i4;
                     this.i2 = this.i13;
                  }
                  else
                  {
                     this.i11 = cmodule.ccode._freelist;
                     this.i23 = li32(this.i3 + 4);
                     this.i23 <<= 2;
                     this.i11 += this.i23;
                     this.i23 = li32(this.i11);
                     si32(this.i23,this.i3);
                     si32(this.i3,this.i11);
                     this.i3 = this.i2;
                     this.i23 = this.i4;
                     this.i2 = this.i13;
                  }
               }
               else
               {
                  this.i1 = 16;
                  this.i3 = this.i2;
                  this.i23 = this.i4;
                  this.i2 = this.i5;
               }
               addr5210:
               this.i4 = this.i23;
               if(this.i3 != 0)
               {
                  this.i8 = cmodule.ccode._freelist;
                  this.i9 = li32(this.i3 + 4);
                  this.i9 <<= 2;
                  this.i8 += this.i9;
                  this.i9 = li32(this.i8);
                  si32(this.i9,this.i3);
                  si32(this.i3,this.i8);
               }
               this.i3 = 0;
               si8(this.i3,this.i2);
               this.i3 = this.i4 + 1;
               si32(this.i3,this.i6);
               if(this.i7 != 0)
               {
                  addr5297:
                  si32(this.i2,this.i7);
                  this.i2 = li32(this.i0);
                  this.i2 |= this.i1;
                  si32(this.i2,this.i0);
               }
               else
               {
                  this.i2 = this.i1;
                  addr52d2:
                  this.i1 = this.i2;
                  this.i2 = li32(this.i0);
                  this.i1 = this.i2 | this.i1;
                  si32(this.i1,this.i0);
               }
               addr52f9:
               mstate.eax = this.i5;
               break;
            case 9:
               this.i23 = mstate.eax;
               mstate.esp += 4;
               this.i17 = 1;
               si32(this.i17,this.i23 + 4);
               this.i17 = 2;
               si32(this.i17,this.i23 + 8);
               §§goto(addr2c26);
            case 10:
               this.i2 = mstate.eax;
               mstate.esp += 4;
               this.i9 = 1;
               si32(this.i9,this.i2 + 4);
               this.i9 = 2;
               si32(this.i9,this.i2 + 8);
               §§goto(addr2eca);
            case 12:
               this.i17 = mstate.eax;
               mstate.esp += 8;
               if(this.i11 == 0)
               {
                  this.i11 = this.i17;
               }
               else
               {
                  this.i18 = cmodule.ccode._freelist;
                  this.i24 = li32(this.i11 + 4);
                  this.i24 <<= 2;
                  this.i18 += this.i24;
                  this.i24 = li32(this.i18);
                  si32(this.i24,this.i11);
                  si32(this.i11,this.i18);
                  this.i11 = this.i17;
               }
               §§goto(addr3128);
            case 13:
               this.i10 = mstate.eax;
               mstate.esp += 8;
               this.i11 = li32(cmodule.ccode._freelist + 4);
               if(this.i11 != 0)
               {
                  this.i16 = li32(this.i11);
                  si32(this.i16,cmodule.ccode._freelist + 4);
               }
               else
               {
                  this.i11 = cmodule.ccode._private_mem;
                  this.i16 = li32(cmodule.ccode._pmem_next);
                  this.i11 = this.i16 - this.i11;
                  this.i11 >>= 3;
                  this.i11 += 4;
                  if(uint(this.i11) > uint(288))
                  {
                     this.i11 = 32;
                     mstate.esp -= 4;
                     si32(this.i11,mstate.esp);
                     state = 14;
                     mstate.esp -= 4;
                     FSM_malloc.start();
                     return;
                  }
                  this.i11 = 1;
                  this.i17 = this.i16 + 32;
                  si32(this.i17,cmodule.ccode._pmem_next);
                  si32(this.i11,this.i16 + 4);
                  this.i11 = 2;
                  si32(this.i11,this.i16 + 8);
                  this.i11 = this.i16;
               }
               addr32db:
               this.i16 = 0;
               si32(this.i16,this.i11 + 12);
               this.i16 = 1;
               si32(this.i16,this.i11 + 20);
               si32(this.i16,this.i11 + 16);
               if(this.i9 <= 0)
               {
                  §§goto(addr356f);
               }
               else
               {
                  §§goto(addr350f);
               }
            case 14:
               this.i11 = mstate.eax;
               mstate.esp += 4;
               this.i16 = 1;
               si32(this.i16,this.i11 + 4);
               this.i16 = 2;
               si32(this.i16,this.i11 + 8);
               §§goto(addr32db);
            case 15:
               this.i10 = mstate.eax;
               mstate.esp += 8;
               addr3378:
               this.i11 = this.i10;
               this.i10 = li32(cmodule.ccode._freelist + 4);
               if(this.i10 != 0)
               {
                  this.i16 = li32(this.i10);
                  si32(this.i16,cmodule.ccode._freelist + 4);
               }
               else
               {
                  this.i10 = cmodule.ccode._private_mem;
                  this.i16 = li32(cmodule.ccode._pmem_next);
                  this.i10 = this.i16 - this.i10;
                  this.i10 >>= 3;
                  this.i10 += 4;
                  if(uint(this.i10) > uint(288))
                  {
                     this.i10 = 32;
                     mstate.esp -= 4;
                     si32(this.i10,mstate.esp);
                     state = 16;
                     mstate.esp -= 4;
                     FSM_malloc.start();
                     return;
                  }
                  this.i10 = 1;
                  this.i17 = this.i16 + 32;
                  si32(this.i17,cmodule.ccode._pmem_next);
                  si32(this.i10,this.i16 + 4);
                  this.i10 = 2;
                  si32(this.i10,this.i16 + 8);
                  this.i10 = this.i16;
               }
               §§goto(addr34ae);
            case 16:
               this.i10 = mstate.eax;
               mstate.esp += 4;
               this.i16 = 1;
               si32(this.i16,this.i10 + 4);
               this.i16 = 2;
               si32(this.i16,this.i10 + 8);
               addr34ae:
               this.i16 = this.i10;
               this.i10 = 0;
               si32(this.i10,this.i16 + 12);
               this.i10 = 1;
               si32(this.i10,this.i16 + 20);
               si32(this.i10,this.i16 + 16);
               if(this.i9 <= 0)
               {
                  this.i10 = this.i11;
                  this.i11 = this.i16;
                  this.i16 = this.i19 < 2 ? 1 : 0;
                  this.i1 = this.i1 == 1 ? 1 : 0;
                  this.i1 &= this.i16;
                  this.i3 = this.i3 > -16444 ? 1 : 0;
                  this.i1 &= this.i3;
                  this.i3 = this.i1 & 1;
                  this.i2 += this.i3;
                  this.i3 = this.i8 + this.i3;
                  §§goto(addr356f);
               }
               else
               {
                  addr350f:
               }
               this.i10 = this.i11;
               this.i11 = this.i16;
               mstate.esp -= 8;
               si32(this.i11,mstate.esp);
               si32(this.i9,mstate.esp + 4);
               state = 17;
               mstate.esp -= 4;
               FSM___pow5mult_D2A.start();
               return;
            case 17:
               this.i11 = mstate.eax;
               mstate.esp += 8;
               addr356f:
               if(this.i9 == 0)
               {
                  this.i8 = 1;
               }
               else
               {
                  this.i8 = li32(this.i11 + 16);
                  this.i8 <<= 2;
                  this.i8 += this.i11;
                  this.i8 = li32(this.i8 + 16);
                  this.i9 = uint(this.i8) < uint(65536) ? 16 : 0;
                  this.i8 <<= this.i9;
                  this.i16 = uint(this.i8) < uint(16777216) ? 8 : 0;
                  this.i8 <<= this.i16;
                  this.i17 = uint(this.i8) < uint(268435456) ? 4 : 0;
                  this.i9 = this.i16 | this.i9;
                  this.i8 <<= this.i17;
                  this.i16 = uint(this.i8) < uint(1073741824) ? 2 : 0;
                  this.i9 |= this.i17;
                  this.i9 |= this.i16;
                  this.i8 <<= this.i16;
                  if(this.i8 <= -1)
                  {
                     this.i8 = this.i9;
                  }
                  else
                  {
                     this.i8 &= 1073741824;
                     this.i9 += 1;
                     this.i8 = this.i8 == 0 ? 32 : this.i9;
                  }
                  this.i8 = 32 - this.i8;
               }
               this.i8 += this.i3;
               this.i8 &= 31;
               this.i9 = 32 - this.i8;
               this.i8 = this.i8 == 0 ? this.i8 : this.i9;
               if(this.i8 >= 5)
               {
                  this.i8 += -4;
                  this.i3 = this.i8 + this.i3;
                  this.i15 = this.i8 + this.i15;
                  this.i2 = this.i8 + this.i2;
                  if(this.i2 <= 0)
                  {
                     this.i2 = this.i3;
                     this.i3 = this.i15;
                     this.i15 = this.i10;
                     §§goto(addr38bb);
                  }
               }
               else
               {
                  if(this.i8 < 4)
                  {
                     this.i8 += 28;
                     this.i3 = this.i8 + this.i3;
                     this.i15 = this.i8 + this.i15;
                     this.i2 = this.i8 + this.i2;
                  }
                  if(this.i2 <= 0)
                  {
                     this.i2 = this.i3;
                     this.i3 = this.i15;
                     this.i15 = this.i10;
                     §§goto(addr38bb);
                  }
               }
               mstate.esp -= 8;
               si32(this.i10,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 18;
               mstate.esp -= 4;
               FSM___lshift_D2A.start();
               return;
            case 18:
               this.i8 = mstate.eax;
               mstate.esp += 8;
               this.i2 = this.i3;
               this.i3 = this.i15;
               this.i15 = this.i8;
               addr38bb:
               this.i8 = this.i15;
               if(this.i2 <= 0)
               {
                  this.i2 = this.i11;
                  §§goto(addr3939);
               }
               mstate.esp -= 8;
               si32(this.i11,mstate.esp);
               si32(this.i2,mstate.esp + 4);
               state = 19;
               mstate.esp -= 4;
               FSM___lshift_D2A.start();
               return;
            case 19:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               addr3939:
               this.i11 = this.i2;
               if(this.i14 != 0)
               {
                  this.i2 = li32(this.i8 + 16);
                  this.i9 = li32(this.i11 + 16);
                  this.i10 = this.i2 - this.i9;
                  if(this.i2 != this.i9)
                  {
                     this.i2 = this.i10;
                  }
                  else
                  {
                     this.i2 = 0;
                     while(true)
                     {
                        this.i10 = this.i2 ^ -1;
                        this.i10 = this.i9 + this.i10;
                        this.i14 = this.i10 << 2;
                        this.i15 = this.i8 + this.i14;
                        this.i14 = this.i11 + this.i14;
                        this.i15 = li32(this.i15 + 20);
                        this.i14 = li32(this.i14 + 20);
                        if(this.i15 != this.i14)
                        {
                           this.i2 = uint(this.i15) < uint(this.i14) ? -1 : 1;
                           break;
                        }
                        this.i2 += 1;
                        if(this.i10 <= 0)
                        {
                           this.i2 = 0;
                           break;
                        }
                     }
                  }
                  if(this.i2 <= -1)
                  {
                     this.i2 = 10;
                     mstate.esp -= 8;
                     si32(this.i8,mstate.esp);
                     si32(this.i2,mstate.esp + 4);
                     state = 20;
                     mstate.esp -= 4;
                     FSM___multadd_D2A.start();
                     return;
                  }
               }
               this.i2 = this.i8;
               this.i8 = this.i13;
               this.i13 = this.i22;
               §§goto(addr3b68);
            case 20:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               this.i13 += -1;
               if(this.i20 != 0)
               {
                  this.i8 = 10;
                  mstate.esp -= 8;
                  si32(this.i23,mstate.esp);
                  si32(this.i8,mstate.esp + 4);
                  state = 21;
                  mstate.esp -= 4;
                  FSM___multadd_D2A.start();
                  return;
               }
               this.i8 = this.i13;
               this.i13 = this.i21;
               §§goto(addr3b68);
               break;
            case 21:
               this.i23 = mstate.eax;
               mstate.esp += 8;
               this.i8 = this.i13;
               this.i13 = this.i21;
               addr3b68:
               if(this.i13 <= 0)
               {
                  if(this.i19 >= 3)
                  {
                     if(this.i13 <= -1)
                     {
                        this.i3 = this.i23;
                        this.i1 = this.i11;
                        break loop30;
                     }
                     this.i1 = 5;
                     mstate.esp -= 8;
                     si32(this.i11,mstate.esp);
                     si32(this.i1,mstate.esp + 4);
                     state = 22;
                     mstate.esp -= 4;
                     FSM___multadd_D2A.start();
                     return;
                  }
               }
               if(this.i20 == 0)
               {
                  mstate.esp -= 8;
                  si32(this.i2,mstate.esp);
                  si32(this.i11,mstate.esp + 4);
                  mstate.esp -= 4;
                  FSM___quorem_D2A.start();
                  §§goto(addr3e18);
               }
               if(this.i3 <= 0)
               {
                  this.i3 = this.i23;
                  §§goto(addr3ee4);
               }
               mstate.esp -= 8;
               si32(this.i23,mstate.esp);
               si32(this.i3,mstate.esp + 4);
               state = 24;
               mstate.esp -= 4;
               FSM___lshift_D2A.start();
               return;
            case 23:
               addr3e18:
               this.i1 = mstate.eax;
               mstate.esp += 8;
               this.i1 += 48;
               si8(this.i1,this.i5);
               this.i3 = this.i5 + 1;
               if(this.i13 <= 1)
               {
                  this.i4 = 0;
                  this.i13 = this.i23;
                  §§goto(addr4cab);
               }
               else
               {
                  addr4b21:
               }
               this.i1 = 0;
               this.i3 = 10;
               mstate.esp -= 8;
               si32(this.i2,mstate.esp);
               si32(this.i3,mstate.esp + 4);
               state = 34;
               mstate.esp -= 4;
               FSM___multadd_D2A.start();
               return;
            case 24:
               this.i3 = mstate.eax;
               mstate.esp += 8;
               addr3ee4:
               this.i1 &= 1;
               if(this.i1 == 0)
               {
                  this.i1 = 0;
                  this.i23 = this.i3;
                  §§goto(addr4037);
               }
               this.i1 = 1;
               this.i23 = li32(this.i3 + 4);
               mstate.esp -= 4;
               si32(this.i23,mstate.esp);
               state = 25;
               mstate.esp -= 4;
               FSM___Balloc_D2A.start();
               return;
            case 26:
               this.i9 = mstate.eax;
               mstate.esp += 8;
               this.i1 = 0;
               this.i23 = this.i3;
               this.i3 = this.i9;
               §§goto(addr4037);
            case 31:
               this.i3 = mstate.eax;
               mstate.esp += 8;
               this.i23 = this.i3;
               §§goto(addr4b03);
            case 33:
               this.i3 = mstate.eax;
               mstate.esp += 8;
               addr4b03:
               this.i1 += 1;
               addr4037:
               this.i9 = this.i3;
               mstate.esp -= 8;
               si32(this.i2,mstate.esp);
               si32(this.i11,mstate.esp + 4);
               mstate.esp -= 4;
               FSM___quorem_D2A.start();
               §§goto(addr407d);
            case 27:
               addr407d:
               this.i3 = mstate.eax;
               mstate.esp += 8;
               this.i10 = li32(this.i2 + 16);
               this.i14 = li32(this.i23 + 16);
               this.i15 = this.i10 - this.i14;
               this.i16 = this.i2 + 16;
               this.i17 = this.i3 + 48;
               this.i18 = this.i12 + this.i1;
               this.i20 = this.i1 + 1;
               if(this.i10 != this.i14)
               {
                  this.i14 = this.i15;
               }
               else
               {
                  this.i10 = 0;
                  while(true)
                  {
                     this.i15 = this.i10 ^ -1;
                     this.i15 = this.i14 + this.i15;
                     this.i21 = this.i15 << 2;
                     this.i22 = this.i2 + this.i21;
                     this.i21 = this.i23 + this.i21;
                     this.i22 = li32(this.i22 + 20);
                     this.i21 = li32(this.i21 + 20);
                     if(this.i22 != this.i21)
                     {
                        this.i10 = uint(this.i22) < uint(this.i21) ? -1 : 1;
                        this.i14 = this.i10;
                        break;
                     }
                     this.i10 += 1;
                     if(this.i15 <= 0)
                     {
                        this.i10 = 0;
                        this.i14 = this.i10;
                        break;
                     }
                  }
               }
               this.i10 = this.i14;
               mstate.esp -= 8;
               si32(this.i11,mstate.esp);
               si32(this.i9,mstate.esp + 4);
               state = 28;
               mstate.esp -= 4;
               FSM___diff_D2A.start();
               return;
            case 11:
               this.i23 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 8;
               si32(this.i23,mstate.esp);
               si32(this.i11,mstate.esp + 4);
               state = 12;
               mstate.esp -= 4;
               FSM___mult_D2A.start();
               return;
            case 22:
               this.i1 = mstate.eax;
               mstate.esp += 8;
               this.i3 = li32(this.i2 + 16);
               this.i4 = li32(this.i1 + 16);
               this.i11 = this.i3 - this.i4;
               if(this.i3 != this.i4)
               {
                  this.i3 = this.i11;
               }
               else
               {
                  this.i3 = 0;
                  while(true)
                  {
                     this.i11 = this.i3 ^ -1;
                     this.i11 = this.i4 + this.i11;
                     this.i13 = this.i11 << 2;
                     this.i12 = this.i2 + this.i13;
                     this.i13 = this.i1 + this.i13;
                     this.i12 = li32(this.i12 + 20);
                     this.i13 = li32(this.i13 + 20);
                     if(this.i12 != this.i13)
                     {
                        break;
                     }
                     this.i3 += 1;
                     if(this.i11 > 0)
                     {
                        continue;
                     }
                     this.i3 = 0;
                  }
                  this.i3 = uint(this.i12) < uint(this.i13) ? -1 : 1;
               }
               if(this.i3 < 1)
               {
                  this.i3 = this.i23;
                  break loop30;
               }
               this.i3 = this.i8;
               this.i4 = this.i23;
               §§goto(addr1f5f);
               break;
            case 25:
               this.i23 = mstate.eax;
               mstate.esp += 4;
               this.i9 = li32(this.i3 + 16);
               this.i10 = this.i23 + 12;
               this.i9 <<= 2;
               this.i14 = this.i3 + 12;
               this.i9 += 8;
               cmodule.ccode.memcpy(this.i10,this.i14,this.i9);
               mstate.esp -= 8;
               si32(this.i23,mstate.esp);
               si32(this.i1,mstate.esp + 4);
               state = 26;
               mstate.esp -= 4;
               FSM___lshift_D2A.start();
               return;
            case 28:
               this.i14 = mstate.eax;
               mstate.esp += 8;
               this.i15 = li32(this.i14 + 12);
               if(this.i15 != 0)
               {
                  this.i15 = 1;
               }
               else
               {
                  this.i15 = li32(this.i16);
                  this.i21 = li32(this.i14 + 16);
                  this.i22 = this.i15 - this.i21;
                  if(this.i15 != this.i21)
                  {
                     this.i15 = this.i22;
                  }
                  else
                  {
                     this.i15 = 0;
                     while(true)
                     {
                        this.i22 = this.i15 ^ -1;
                        this.i22 = this.i21 + this.i22;
                        this.i24 = this.i22 << 2;
                        this.i25 = this.i2 + this.i24;
                        this.i24 = this.i14 + this.i24;
                        this.i25 = li32(this.i25 + 20);
                        this.i24 = li32(this.i24 + 20);
                        if(this.i25 != this.i24)
                        {
                           this.i15 = uint(this.i25) < uint(this.i24) ? -1 : 1;
                           break;
                        }
                        this.i15 += 1;
                        if(this.i22 <= 0)
                        {
                           this.i15 = 0;
                           break;
                        }
                     }
                  }
               }
               if(this.i14 != 0)
               {
                  this.i21 = cmodule.ccode._freelist;
                  this.i22 = li32(this.i14 + 4);
                  this.i22 <<= 2;
                  this.i21 += this.i22;
                  this.i22 = li32(this.i21);
                  si32(this.i22,this.i14);
                  si32(this.i14,this.i21);
               }
               this.i14 = this.i15 | this.i19;
               loop41:
               while(true)
               {
                  while(true)
                  {
                     if(this.i14 == 0)
                     {
                        this.i14 = li32(this.i4);
                        this.i14 &= 1;
                        if(this.i14 == 0)
                        {
                           if(this.i17 == 57)
                           {
                              break;
                           }
                           if(this.i10 <= 0)
                           {
                              this.i3 = li32(this.i16);
                              if(this.i3 <= 1)
                              {
                                 this.i3 = li32(this.i2 + 20);
                                 if(this.i3 == 0)
                                 {
                                    this.i4 = 0;
                                    this.i1 += this.i5;
                                    si8(this.i17,this.i18);
                                    this.i10 = this.i1 + 1;
                                    this.i13 = this.i23;
                                    this.i3 = this.i8;
                                    this.i8 = this.i4;
                                    this.i4 = this.i9;
                                    this.i1 = this.i11;
                                    this.i11 = this.i10;
                                    break loop41;
                                 }
                              }
                              this.i4 = 16;
                              this.i1 += this.i5;
                              si8(this.i17,this.i18);
                              this.i10 = this.i1 + 1;
                              this.i13 = this.i23;
                              this.i3 = this.i8;
                              this.i8 = this.i4;
                              this.i4 = this.i9;
                              this.i1 = this.i11;
                              this.i11 = this.i10;
                              break loop41;
                           }
                           this.i4 = 32;
                           this.i1 += this.i5;
                           this.i3 += 49;
                           si8(this.i3,this.i18);
                           this.i10 = this.i1 + 1;
                           this.i13 = this.i23;
                           this.i3 = this.i8;
                           this.i8 = this.i4;
                           this.i4 = this.i9;
                           this.i1 = this.i11;
                           this.i11 = this.i10;
                           break loop41;
                        }
                     }
                     if(this.i10 >= 0)
                     {
                        this.i10 |= this.i19;
                        if(this.i10 == 0)
                        {
                           this.i10 = li32(this.i4);
                           this.i10 &= 1;
                           if(this.i10 == 0)
                           {
                              §§goto(addr4569);
                           }
                        }
                        if(this.i15 >= 1)
                        {
                           if(this.i17 != 57)
                           {
                              this.i4 = 32;
                              this.i1 += this.i5;
                              this.i3 = this.i17 + 1;
                              si8(this.i3,this.i18);
                              this.i12 = this.i1 + 1;
                              this.i13 = this.i23;
                              this.i3 = this.i8;
                              this.i8 = this.i4;
                              this.i4 = this.i9;
                              this.i1 = this.i11;
                              this.i11 = this.i12;
                              break loop41;
                           }
                           break;
                        }
                        si8(this.i17,this.i18);
                        this.i3 = this.i1 + 1;
                        if(this.i20 != this.i13)
                        {
                           this.i3 = 10;
                           mstate.esp -= 8;
                           si32(this.i2,mstate.esp);
                           si32(this.i3,mstate.esp + 4);
                           state = 30;
                           mstate.esp -= 4;
                           FSM___multadd_D2A.start();
                           return;
                        }
                        this.i1 = this.i5 + this.i3;
                        this.i3 = this.i1;
                        this.i1 = this.i17;
                        this.i13 = this.i9;
                        this.i4 = this.i23;
                        §§goto(addr4cab);
                     }
                     addr4569:
                     if(this.i15 <= 0)
                     {
                        this.i3 = 0;
                        this.i4 = this.i17;
                        addr4740:
                        this.i12 = this.i3;
                        this.i3 = this.i4;
                        this.i4 = li32(this.i2 + 16);
                        if(this.i4 <= 1)
                        {
                           this.i4 = li32(this.i2 + 20);
                           if(this.i4 == 0)
                           {
                              this.i1 += this.i5;
                              si8(this.i3,this.i18);
                              this.i15 = this.i1 + 1;
                              this.i13 = this.i23;
                              this.i3 = this.i8;
                              this.i8 = this.i12;
                              this.i4 = this.i9;
                              this.i1 = this.i11;
                              this.i11 = this.i15;
                              break loop41;
                           }
                        }
                        this.i4 = 16;
                        this.i1 += this.i5;
                        si8(this.i3,this.i18);
                        this.i12 = this.i1 + 1;
                        this.i13 = this.i23;
                        this.i3 = this.i8;
                        this.i8 = this.i4;
                        this.i4 = this.i9;
                        this.i1 = this.i11;
                        this.i11 = this.i12;
                        break loop41;
                     }
                     this.i4 = 1;
                     mstate.esp -= 8;
                     si32(this.i2,mstate.esp);
                     si32(this.i4,mstate.esp + 4);
                     state = 29;
                     mstate.esp -= 4;
                     FSM___lshift_D2A.start();
                     return;
                  }
                  addr48ac:
                  this.i3 = 57;
                  this.i4 = this.i1 + this.i5;
                  si8(this.i3,this.i18);
                  this.i3 = this.i4 + 1;
                  this.i1 = this.i12 + this.i1;
                  this.i4 = this.i23;
                  this.i13 = this.i9;
                  addr48f9:
                  this.i23 = this.i13;
                  this.i9 = this.i3;
                  this.i3 = this.i1;
                  if(this.i3 != this.i5)
                  {
                     this.i1 = this.i4;
                     this.i4 = this.i23;
                     while(true)
                     {
                        this.i23 = this.i4;
                        this.i9 = this.i3;
                        this.i3 = li8(this.i9 + -1);
                        this.i10 = this.i9 + -1;
                        if(this.i3 != 57)
                        {
                           break;
                        }
                        this.i4 = this.i1;
                        this.i13 = this.i23;
                        this.i3 = this.i9;
                        this.i1 = this.i10;
                        §§goto(addr48f9);
                        this.i1 = this.i4;
                        this.i4 = this.i23;
                     }
                     this.i4 = 32;
                     this.i3 += 1;
                     si8(this.i3,this.i10);
                     this.i13 = this.i1;
                     this.i3 = this.i8;
                     this.i8 = this.i4;
                     this.i4 = this.i23;
                     this.i1 = this.i11;
                     this.i11 = this.i9;
                     break;
                     addr4e2e:
                  }
                  this.i1 = 49;
                  si8(this.i1,this.i3);
                  this.i1 = 32;
                  this.i3 = this.i8 + 1;
                  this.i13 = this.i4;
                  this.i8 = this.i1;
                  this.i4 = this.i23;
                  this.i1 = this.i11;
                  this.i11 = this.i9;
                  break;
               }
               §§goto(addr5019);
            case 29:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               this.i4 = li32(this.i2 + 16);
               this.i13 = li32(this.i11 + 16);
               this.i15 = this.i4 - this.i13;
               if(this.i4 != this.i13)
               {
                  this.i4 = this.i15;
               }
               else
               {
                  this.i4 = 0;
                  while(true)
                  {
                     this.i15 = this.i4 ^ -1;
                     this.i15 = this.i13 + this.i15;
                     this.i19 = this.i15 << 2;
                     this.i20 = this.i2 + this.i19;
                     this.i19 = this.i11 + this.i19;
                     this.i20 = li32(this.i20 + 20);
                     this.i19 = li32(this.i19 + 20);
                     if(this.i20 != this.i19)
                     {
                        break;
                     }
                     this.i4 += 1;
                     if(this.i15 > 0)
                     {
                        continue;
                     }
                     this.i4 = 0;
                  }
                  this.i4 = uint(this.i20) < uint(this.i19) ? -1 : 1;
               }
               while(true)
               {
                  if(this.i4 <= 0)
                  {
                     if(this.i4 == 0)
                     {
                        this.i4 = this.i17 & 1;
                        if(this.i4 != 0)
                        {
                           addr4720:
                           this.i4 = this.i3 + 49;
                           if(this.i4 != 58)
                           {
                              this.i3 = 32;
                              break;
                           }
                           §§goto(addr48ac);
                        }
                     }
                     this.i3 = 32;
                     this.i4 = this.i17;
                     break;
                  }
                  §§goto(addr4720);
               }
               §§goto(addr4740);
            case 30:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               if(this.i23 == this.i9)
               {
                  this.i3 = 10;
                  mstate.esp -= 8;
                  si32(this.i9,mstate.esp);
                  si32(this.i3,mstate.esp + 4);
                  state = 31;
                  mstate.esp -= 4;
                  FSM___multadd_D2A.start();
                  return;
               }
               this.i3 = 10;
               mstate.esp -= 8;
               si32(this.i23,mstate.esp);
               si32(this.i3,mstate.esp + 4);
               state = 32;
               mstate.esp -= 4;
               FSM___multadd_D2A.start();
               return;
               break;
            case 32:
               this.i23 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 8;
               si32(this.i9,mstate.esp);
               si32(this.i3,mstate.esp + 4);
               state = 33;
               mstate.esp -= 4;
               FSM___multadd_D2A.start();
               return;
            case 34:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               mstate.esp -= 8;
               si32(this.i2,mstate.esp);
               si32(this.i11,mstate.esp + 4);
               mstate.esp -= 4;
               FSM___quorem_D2A.start();
            case 35:
               this.i3 = mstate.eax;
               mstate.esp += 8;
               this.i4 = this.i3 + 48;
               this.i3 = this.i12 + this.i1;
               si8(this.i4,this.i3 + 1);
               this.i3 = this.i1 + 1;
               this.i1 += 2;
               if(this.i1 >= this.i13)
               {
                  this.i9 = 0;
                  this.i1 = this.i3 << 0;
                  this.i1 += this.i5;
                  this.i1 += 1;
                  this.i3 = this.i1;
                  this.i1 = this.i4;
                  this.i13 = this.i23;
                  this.i4 = this.i9;
                  addr4cab:
                  this.i23 = this.i13;
                  this.i13 = 1;
                  mstate.esp -= 8;
                  si32(this.i2,mstate.esp);
                  si32(this.i13,mstate.esp + 4);
                  state = 36;
                  mstate.esp -= 4;
                  FSM___lshift_D2A.start();
                  return;
               }
               this.i1 = this.i3;
               §§goto(addr4b21);
               break;
            case 36:
               this.i2 = mstate.eax;
               mstate.esp += 8;
               this.i13 = li32(this.i2 + 16);
               this.i9 = li32(this.i11 + 16);
               this.i10 = this.i13 - this.i9;
               if(this.i13 != this.i9)
               {
                  this.i13 = this.i10;
               }
               else
               {
                  this.i13 = 0;
                  while(true)
                  {
                     this.i10 = this.i13 ^ -1;
                     this.i10 = this.i9 + this.i10;
                     this.i12 = this.i10 << 2;
                     this.i14 = this.i2 + this.i12;
                     this.i12 = this.i11 + this.i12;
                     this.i14 = li32(this.i14 + 20);
                     this.i12 = li32(this.i12 + 20);
                     if(this.i14 != this.i12)
                     {
                        this.i13 = uint(this.i14) < uint(this.i12) ? -1 : 1;
                        break;
                     }
                     this.i13 += 1;
                     if(this.i10 <= 0)
                     {
                        this.i13 = 0;
                        break;
                     }
                  }
               }
               if(this.i13 < 1)
               {
                  if(this.i13 == 0)
                  {
                     this.i1 &= 1;
                     if(this.i1 != 0)
                     {
                        addr4e1a:
                        this.i1 = this.i4;
                        this.i4 = this.i23;
                        §§goto(addr4e2e);
                     }
                  }
                  this.i1 = li32(this.i2 + 16);
                  while(true)
                  {
                     if(this.i1 <= 1)
                     {
                        this.i1 = li32(this.i2 + 20);
                        if(this.i1 == 0)
                        {
                           this.i1 = 0;
                           break;
                        }
                     }
                     this.i1 = 16;
                     break;
                  }
                  this.i13 = 0;
                  do
                  {
                     this.i9 = this.i13 ^ -1;
                     this.i9 = this.i3 + this.i9;
                     this.i9 = li8(this.i9);
                     this.i13 += 1;
                  }
                  while(this.i9 == 48);
                  this.i13 += -1;
                  this.i9 = this.i3 - this.i13;
                  this.i13 = this.i4;
                  this.i3 = this.i8;
                  this.i8 = this.i1;
                  this.i4 = this.i23;
                  this.i1 = this.i11;
                  this.i11 = this.i9;
                  break loop41;
               }
               §§goto(addr4e1a);
            default:
               throw "Invalid state in ___gdtoa";
         }
         mstate.esp = mstate.ebp;
         mstate.ebp = li32(mstate.esp);
         mstate.esp += 4;
         mstate.esp += 4;
         mstate.gworker = caller;
      }
   }
}

