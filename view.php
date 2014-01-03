<?php
session_start();
?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<title>Form Testing</title>
<script type="text/javascript" src="js/jquery.js"></script>
<script type="text/javascript" src="js/var.js"></script>
<script type="text/javascript" src="js/form.js"></script>
<script type="text/javascript" src="js/Calendar.js"></script>
<script type="text/javascript" src="js/xmlGen.js"></script>
<script src="http://code.jquery.com/ui/1.10.3/jquery-ui.js"></script>
<link rel="stylesheet" href="http://code.jquery.com/ui/1.10.3/themes/smoothness/jquery-ui.css" />
<link rel="stylesheet" href="css/form.css" />

  <script>
  $(function() {
	 $( "#dialog" ).dialog({
		  modal: true,
		  autoOpen: false,
		  show: {
			effect: "blind",
			duration: 1000
		  },
		  hide: {
			effect: "explode",
			duration: 1000
		  }
		});
	});
  </script>
</head>

<body>
   <form action="StoreData.php" method="post">
<div id="formArea" class="">

<?php

	$counter = 0;
	include_once "lib/lib.php";
	$file = $_GET['xml'];
	if($file!=NULL)
	{
		$fil = file_get_contents($file);
		$xml = new SimpleXMLElement($fil);
		$tab = $xml->page->tab;

               if(isset($_SESSION['SQLTableName'])){   
                   unset($_SESSION[' SQLTableName']);                    
                }
                $_SESSION['SQLTableName'] =  getTableNamebyDocLink($file);
			echo "<div id=\"formTitleWarp\"><div id=\"formtitle\" >".$xml->title."</div></div>";

		for ($i =0;$i<count($tab);$i++){
			switch ($tab[$i]->type) {
				case "text":
					textClient($tab[$i],$i);
					break;
                                case "date":
					dateClient($tab[$i],$i);
					break;
                                case "SingleSelect":
					SingleSelectClient($tab[$i],$i);
                                        break;
			}
		}
		echo "<div id=\"Loadedfilename\" style=\"display:none;\">".$file."</div>";
        }
        else {
     echo " Form is not found, or you do not have the permission to check out! ";
        }
	
?>

</div>
<div id="addForm" class="">
  <div id="addForm2" class="">
 	<!-- <button id="opener">Open Dialog</button>-->
        <input type="submit" value="Submit the form" ></input>

  </div>
</div>
</form>
<div id="dialog" title="Basic dialog">
</div>

</body>

</html>