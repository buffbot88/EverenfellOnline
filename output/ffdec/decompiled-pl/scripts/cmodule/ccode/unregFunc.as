package cmodule.ccode
{
   public function unregFunc(param1:int) : void
   {
      if(param1 + 1 == cmodule.ccode.gstate.funcs.length)
      {
         cmodule.ccode.gstate.funcs.pop();
      }
   }
}

