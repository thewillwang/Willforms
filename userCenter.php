<?php
session_start();
include_once "lib/lib.php";
sql_login();

checkLogin();
?> 
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<title>Form Testing</title>
<script type="text/javascript" src="js/jquery.js"></script>
<script type="text/javascript" src="js/var.js"></script>
<script type="text/javascript" src="js/form.js"></script>
<script type="text/javascript" src="js/xmlGen.js"></script>
<script src="http://code.jquery.com/ui/1.10.3/jquery-ui.js"></script>
<link rel="stylesheet" href="http://code.jquery.com/ui/1.10.3/themes/smoothness/jquery-ui.css" />
<link rel="stylesheet" href="css/form.css" />

 <script>
  $(function() {
    $( "#tabs" ).tabs();
  });
  </script>
</head>
<body>
<?php 
    		 echo "<div id='usercenter'>Hello <a href=userCenter.php >".$username.
			"</a>,   <a href=logout.php id='logout'>Logout</a></div>";
?>
<div id="tabs">
  <ul>
    <li><a href="#tabs-1">Form List</a></li>
    <li><a href="#tabs-2">Proin dolor</a></li>
    <li><a href="#tabs-3">Aenean lacinia</a></li>
  </ul>
  <div id="tabs-1">
  <?php
  
        $username = $_SESSION['username'];
 	$check = mysql_query( "SELECT docPath,docName,status FROM users, userDocs WHERE users.userID = userDocs.userID AND users.username = '".$username."'" );
	 while ( $info = mysql_fetch_array( $check ) ) {
		echo "<table ><tr>
                        <td>";
                    if($info[ 'status' ] == '1')
                            echo "<a>".$info[ 'docName' ]." </a> <br/>";
                        else {
                            echo "<a href=\"form.php?xml=".$info[ 'docPath' ]."\">".$info[ 'docName' ]." </a> <br/>";
                        }
                        echo"
                        </td>
                        <td>
                            <a href=\"view.php?xml=".$info[ 'docPath' ]."\">preView</a> 
                        </td> ";
                        if($info[ 'status' ] == '1'){
                           echo "   <td><a href=\"results.php?xml=".$info[ 'docPath' ]."\">viewresult</a> </td>";
                           echo" <td><button  onclick=\"save.extract.del('".$info[ 'docPath' ]."');\" >+delete</button ></td>";
                        }
                       echo" </tr></table>";
	 }
  ?>
  <br/>
  <a href="form.php" id="addform" >+new</a>
  </div>
  <div id="tabs-2">
    <p>Morbi tincidunt, dui sit amet facilisis feugiat, odio metus gravida ante, ut pharetra massa metus id nunc. Duis scelerisque molestie turpis. Sed fringilla, massa eget luctus malesuada, metus eros molestie lectus, ut tempus eros massa ut dolor. Aenean aliquet fringilla sem. Suspendisse sed ligula in ligula suscipit aliquam. Praesent in eros vestibulum mi adipiscing adipiscing. Morbi facilisis. Curabitur ornare consequat nunc. Aenean vel metus. Ut posuere viverra nulla. Aliquam erat volutpat. Pellentesque convallis. Maecenas feugiat, tellus pellentesque pretium posuere, felis lorem euismod felis, eu ornare leo nisi vel felis. Mauris consectetur tortor et purus.</p>
  </div>
  <div id="tabs-3">
    <p>Mauris eleifend est et turpis. Duis id erat. Suspendisse potenti. Aliquam vulputate, pede vel vehicula accumsan, mi neque rutrum erat, eu congue orci lorem eget lorem. Vestibulum non ante. Class aptent taciti sociosqu ad litora torquent per conubia nostra, per inceptos himenaeos. Fusce sodales. Quisque eu urna vel enim commodo pellentesque. Praesent eu risus hendrerit ligula tempus pretium. Curabitur lorem enim, pretium nec, feugiat nec, luctus a, lacus.</p>
    <p>Duis cursus. Maecenas ligula eros, blandit nec, pharetra at, semper at, magna. Nullam ac lacus. Nulla facilisi. Praesent viverra justo vitae neque. Praesent blandit adipiscing velit. Suspendisse potenti. Donec mattis, pede vel pharetra blandit, magna ligula faucibus eros, id euismod lacus dolor eget odio. Nam scelerisque. Donec non libero sed nulla mattis commodo. Ut sagittis. Donec nisi lectus, feugiat porttitor, tempor ac, tempor vitae, pede. Aenean vehicula velit eu tellus interdum rutrum. Maecenas commodo. Pellentesque nec elit. Fusce in lacus. Vivamus a libero vitae lectus hendrerit hendrerit.</p>
  </div>
</div>

</body>
</html>
