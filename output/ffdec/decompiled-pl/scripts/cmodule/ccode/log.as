package cmodule.ccode
{
   public function log(param1:int, param2:String) : void
   {
      if(param1 < cmodule.ccode.glogLvl)
      {
         trace(param2);
      }
   }
}

