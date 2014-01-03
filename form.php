<?php
session_start();
include_once "lib/lib.php";
checkLogin();
?> 

<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<title>Form Testing</title> 
<script type="text/javascript" src="js/jquery.js"></script>
<script type="text/javascript" src="js/var.js"></script>
<script type="text/javascript" src="js/Calendar.js"></script>
<script type="text/javascript" src="js/form.js"></script>
<script type="text/javascript" src="js/xmlGen.js"></script>
<script src="http://code.jquery.com/ui/1.10.3/jquery-ui.js"></script>
<link rel="stylesheet" href="http://code.jquery.com/ui/1.10.3/themes/smoothness/jquery-ui.css" />
<link rel="stylesheet" href="css/form.css" />

  <script>
  $(function() {
	 $( "#dialog" ).dialog({
                  width: 500,
                  height:500,
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
<?php 

    		  echo "<div id='usercenter'>Hello <a href=userCenter.php >".$username.
			"</a>, <a href=logout.php id='logout'>Logout</a></div>";
?>
<div id="formArea" class="">

<?php
    $titileEdit = "<button onclick=\"xx.util.titleEdit();\" class=\"ui-button ui-widget ui-state-default ui-corner-all ui-button-icon-only ui-dialog-titlebar-close\" 
    role=\"button\" aria-disabled=\"false\" title=\"edit\" id=\"edittitle\">
    <span class=\"ui-button-icon-primary ui-icon ui-icon-pencil\"></span>
    <span class=\"ui-button-text\">edit</span></button>";

	$counter = 0;
	include_once "lib/lib.php";
	$file = $_GET['xml'];
	if($file!=NULL)
	{
		$fil = file_get_contents($file);
		$xml = new SimpleXMLElement($fil);
		$tab = $xml->page->tab;
			echo "<div id=\"formTitleWarp\"><div id=\"formtitle\" >".$xml->title."</div>".$titileEdit." </div>";

		for ($i =0;$i<count($tab);$i++){
			switch ($tab[$i]->type) {
				case "text":
					text($tab[$i],$i);
					break;
                                case "date":
					DateForm($tab[$i],$i);
					break;
                                case "SingleSelect":
					SingalSelect($tab[$i],$i);
				break;
			}
		}
		
		echo "<script> counter = ".count($tab).";</script>";
	}
	else{
					echo "<div id=\"formTitleWarp\"><div id=\"formtitle\" >Form Title</div>".$titileEdit."</div>";
		}
	echo "<div id=\"Loadedfilename\" style=\"display:none;\">".$file."</div>";
	
?>

</div>
<div id="addForm" class="">



  <div id="addForm2" class="">
 	<!-- <button id="opener">Open Dialog</button>-->
    <a onclick="xx.text.insert(counter);" id="addform" >+text</a>
    <a onclick="xx.SingleChoice.insert(counter);" id="addform" >+choices</a>
    <a onclick="xx.date.insert(counter);" id="addform" >+date</a>
    <a onclick="save.extract.ToStr();" id="addform" >+save</a>
    <a onclick="save.extract.del();" id="addform" >+delete</a>
    <a onclick="publish.done();" id="addform" >+publish</a>
   <!-- <button onclick="xx.selection.insert(counter);" >selection</button>-->
   <!-- <button onclick="xx.date.insert(counter);" >date</button>-->
   <!-- <button onclick="xx.number.insert(counter);" >number</button>-->
  </div> 
</div>
 
<div id="dialog" title="Basic dialog">
</div>

</body>

</html>