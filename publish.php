<?php
session_start();
include_once "lib/lib.php";

    sql_login();
    publishForm();
function publishForm(){
        //error_log("data");
	$dataTableName = array();
	$dataTableType = array();
        $userName = $_SESSION['username'];
        // set sql table attribute and type
	$filePath = GenExp($_POST['filePath']."");
	if($filePath!=NULL)
	{
		$fil = file_get_contents($filePath);
		$xml = new SimpleXMLElement($fil);
		$tab = $xml->page->tab;
		for ($i =0;$i<count($tab);$i++){
                  $dataTableName[$i] = $tab[$i]->dbtablename;
                  $dataTableType[$i] = $tab[$i]->type;
		}
        }
        
        $docID= getdocID($userName, $filePath);
	$query = " CREATE TABLE ".$userName."_".$docID."(";

	if(count($dataTableName) != count($dataTableType))
	{
                      //      error_log("Data Table are not matching Data table Type");
		die("Data Table are not matching Data table Type");
	}
	//error_log("table count: ".count($dataTableName));
	for ($i=0;$i < count($dataTableName);$i++){
		
		$query .= SQL_attr(GenExp($dataTableName[$i]),GenExp($dataTableType[$i]."")).",";
		//$query .= ($i < (count($dataTableName)-1)) ? "," : "";
	}
        	//error_log("here");
	$query.="  CreateTime Datetime DEFAULT 0,LastUpdateTime TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP";
	$query .=");";
	error_log($query);

	mysql_query($query) or error_log(mysql_error());
	error_log("here");
	changeFormStatus($filePath);
}
/*
	input: $dataTableName : sql table attribute name ,$dataTableType attribut data type
*/
function SQL_attr($dataTableName,$dataTableType)
{
		$attriProperty = " ".mysql_escape_string($dataTableName)." ";
		switch ($dataTableType)
		{
			case "text":
			$attriProperty .= " TEXT";
			break;
                    	case "SingleSelect":
			$attriProperty .= " TEXT";
                        case "date":
			$attriProperty .= " TEXT";
			break;
			
		}
                
                return $attriProperty;
}

function changeFormStatus($filePath){
	$query = "UPDATE userDocs SET `status`= '1' WHERE docID = '".getdocID($_SESSION['username'],$filePath)."'";
	mysql_query($query);	
       // error_log($query);
}

function getdocID($userName,$filePath){
        $userID = mysql_query( "SELECT userID FROM users WHERE username = '".$userName."'" );
	$info = mysql_fetch_array( $userID );
	$query = "SELECT `docID` FROM userDocs  WHERE `userID` = '".$info['userID']."' AND `docPath` ='".$filePath."'";
        
        $infos = mysql_fetch_array(mysql_query($query));
        return $infos['docID'];
}

?>