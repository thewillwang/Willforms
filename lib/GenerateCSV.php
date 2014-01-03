<?php
        //include_once "Config.php";
        include_once "lib.php";
        include_once 'Excel/Classes/PHPExcel.php';

generateCSV($_GET['xml']);

function generateCSV($filename){
        

	$counter = 0;
	$file = "../".$filename;
	if($file!=NULL)
	{
                $CSV = array();
		$fil = file_get_contents($file);
		$xml = new SimpleXMLElement($fil);
		$tab = $xml->page->tab;
                
                $tablname =  getTableNamebyDocLink($filename);
                sql_login();
                
                $CSVtitle = array();
                for ($i =0;$i<count($tab);$i++){
                array_push($CSVtitle,$tab[$i]->dataname);
                }
                array_push($CSV,$CSVtitle);
            
                
 
                $qeury = "select * from ".$tablname;
                $result = mysql_query($qeury);
                      if(!$result) {
                             echo "Query failed\n<br><b>$qeury</b>\n";
                             echo mysql_error(); // (Is that not the name)
                        }
                      $rowCount = 2;
                 while( $row = mysql_fetch_array($result)){
                     
                        $CSVdetail = array();
                        for ($i =0;$i<count($tab);$i++){
                            array_push($CSVdetail,$row["".$tab[$i]->dbtablename]);
                        }
                    array_push($CSV,$CSVdetail);
                }
                header('Content-Type: text/csv');
                header('Content-Disposition: attachment;filename="'.$xml->title.'.csv"');
                header('Cache-Control: max-age=0');
                header('Content-language: zh');
                
                $output = fopen("php://output", "w");
                     foreach ($CSV as $row) {
                             fputcsv($output, $row);
                    }
                fclose($output);
                   
                

        }          
        else {
        echo " Form is not found, or you do not have the permission to check out! ";
        }
}
?>