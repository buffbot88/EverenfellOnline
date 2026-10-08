package cmodule.ccode
{
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   internal class GLEByteArrayProvider
   {
      
      public function GLEByteArrayProvider()
      {
         super();
      }
      
      public static function get() : ByteArray
      {
         var result:ByteArray = null;
         try
         {
            result = cmodule.ccode.gdomainClass.currentDomain.domainMemory;
         }
         catch(e:*)
         {
         }
         if(!result)
         {
            result = new LEByteArray();
            try
            {
               result.length = cmodule.ccode.gdomainClass.MIN_DOMAIN_MEMORY_LENGTH;
               cmodule.ccode.gdomainClass.currentDomain.domainMemory = result;
            }
            catch(e:*)
            {
               cmodule.ccode.log(3,"Not using domain memory");
            }
         }
         return result;
      }
   }
}

