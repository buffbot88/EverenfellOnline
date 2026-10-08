package cmodule.ccode
{
   public function regPostStaticInit(param1:Function) : void
   {
      if(!cmodule.ccode.gpostStaticInits)
      {
         cmodule.ccode.gpostStaticInits = [];
      }
      cmodule.ccode.gpostStaticInits.push(param1);
   }
}

