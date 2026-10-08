package cmodule.ccode
{
   public function regPreStaticInit(param1:Function) : void
   {
      if(!cmodule.ccode.gpreStaticInits)
      {
         cmodule.ccode.gpreStaticInits = [];
      }
      cmodule.ccode.gpreStaticInits.push(param1);
   }
}

