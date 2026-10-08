package cmodule.ccode
{
   public function establishEnv() : void
   {
      var ns:Namespace = null;
      try
      {
         ns = new Namespace("avmplus");
         cmodule.ccode.gdomainClass = ns::["Domain"];
         cmodule.ccode.gshell = true;
      }
      catch(e:*)
      {
      }
      if(!cmodule.ccode.gdomainClass)
      {
         ns = new Namespace("flash.system");
         cmodule.ccode.gdomainClass = ns::["ApplicationDomain"];
      }
   }
}

